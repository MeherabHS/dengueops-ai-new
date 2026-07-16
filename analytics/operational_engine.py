"""
operational_engine.py
=====================
DengueOps AI — Phase 5: Operational Decision-Support Engine

Converts the uncertainty-aware dengue forecast into zone-level risk allocation,
supply depletion timelines (SDH), LOS-based bed pressure estimates,
vulnerability-gated priority scores, inventory alerts, and plain-language
operational recommendations.

Outputs:
    data/directives.json

Design principles:
    1. Consumables vs. cumulative resources are modelled differently:

       Consumables (NS1/RDT kits, IV fluids):
           Demand scales with forecast growth factor because surge volume
           directly drives throughput of diagnostic kits and IV administrations.
           SDH = current_stock / (baseline_daily_consumption * growth_factor)
           At higher growth factor, kits run out faster.

       Beds (cumulative resource):
           Beds are not consumed per patient — they are held for the duration
           of a patient's stay (avg_length_of_stay days). Bed pressure is
           therefore a function of how many concurrent patients occupy beds,
           not how fast beds are "used up". Modelling beds as SDH would
           overstate depletion risk; the correct measure is projected
           occupancy versus available capacity.

    2. Planning-priority scoring is an unsupported prototype heuristic:

       The governed executable structural-plus-growth expression is retained
       for benchmark compatibility only. It is not epidemiological risk, an
       official allocation rule, or an institution-approved priority.

    3. Spatial exposure allocation is a heuristic:

       City-level forecast cases are allocated to zones via a normalized
       exposure index. Under sub-city data constraints (no granular epi
       surveillance by ward), this is a transparent prototype approximation.
       It should not be interpreted as a precise case count prediction per zone.

Usage:
    python analytics/operational_engine.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from provenance import artifact_provenance
from formula_registry import (
    FormulaRegistryError, assert_formulas_allowed, build_formula_metadata, current_deployment_gate,
    get_parameter,
)

# ── I/O paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
FORECAST_PATH   = ROOT / "data" / "forecast_output.json"
ZONES_PATH      = ROOT / "data" / "zones.json"
FACILITIES_PATH = ROOT / "data" / "facilities.json"
INVENTORY_PATH  = ROOT / "data" / "inventory.json"
DIRECTIVES_PATH = ROOT / "data" / "directives.json"

# ── Exposure index component weights ──────────────────────────────────────────
EXPOSURE_WEIGHTS = {
    "population_share": float(get_parameter("OPS.EXPOSURE.COMPOSITION", "population_weight")),
    "density_weight": float(get_parameter("OPS.EXPOSURE.COMPOSITION", "density_weight")),
    "facility_pressure_weight": float(get_parameter("OPS.EXPOSURE.COMPOSITION", "facility_pressure_weight")),
    "mobility_corridor_weight": float(get_parameter("OPS.EXPOSURE.COMPOSITION", "mobility_weight")),
}

# ── Priority category thresholds ──────────────────────────────────────────────
PRIORITY_CATEGORIES = [
    (float(get_parameter("OPS.PRIORITY.CATEGORIES", "routine_max")), "Routine"),
    (float(get_parameter("OPS.PRIORITY.CATEGORIES", "moderate_max")), "Moderate"),
    (float(get_parameter("OPS.PRIORITY.CATEGORIES", "high_max")), "High"),
    (101, "Critical"),
]

OPERATIONAL_FORMULA_IDS = (
    "FORECAST.GROWTH_FACTOR", "FORECAST.GROWTH_CATEGORY", "FORECAST.GROWTH_SCORE",
    "FORECAST.RMSE_SENSITIVITY", "OPS.EXPOSURE.COMPOSITION", "OPS.EXPOSURE.ANOMALY",
    "OPS.ALLOCATION.ZONE", "OPS.ALLOCATION.FACILITY", "OPS.ADMISSION_FRACTION",
    "OPS.BED.DEMAND", "OPS.BED.DEFICIT", "OPS.STOCK.DYNAMIC_DEMAND",
    "OPS.STOCK.SDH", "OPS.STOCK.THRESHOLDS", "OPS.PRIORITY.SCORE",
    "OPS.PRIORITY.CATEGORIES", "OPS.DIRECTIVE.TRIGGERS",
)

PLANNING_TIER_LABELS = {
    "Routine": "Routine simulated planning tier",
    "Moderate": "Moderate simulated planning tier",
    "High": "High simulated planning tier",
    "Critical": "Highest simulated planning tier",
}

# ── Inventory item type recognition keywords ──────────────────────────────────
NS1_KEYWORDS = ("ns1", "rdt")
IVF_KEYWORDS = ("iv fluid", "iv", "fluid")


# ─────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_json(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"Required file not found: {path}\n"
            "Ensure all earlier phases have been run:\n"
            "  python analytics/forecast_model.py\n"
            "  python analytics/uncertainty_engine.py"
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────────────────
# Exposure weight computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_exposure_weights(zones: list[dict]) -> list[dict]:
    """
    Ensure each zone has an exposure_index, apply the anomaly adjustment,
    then normalize so all adjusted_exposure values sum to 1.

    If exposure_index is already stored in the zone (computed during data
    generation), it is used directly. Otherwise it is re-derived from
    component weights using EXPOSURE_WEIGHTS.

    adjusted_exposure = exposure_index + current_anomaly_adjustment

    The anomaly adjustment represents week-specific deviations (e.g. local
    flooding, vector activity reports). Adding it to the base index lifts
    zones that are experiencing above-baseline conditions this period.
    After normalization, the sum of adjusted_exposures across all zones = 1,
    so they form a valid allocation weight vector.

    Parameters
    ----------
    zones : list[dict]
        Raw zone records from zones.json.

    Returns
    -------
    list[dict]
        Zone records enriched with adjusted_exposure and normalized_exposure.
    """
    enriched = []
    for z in zones:
        # Use stored exposure_index if present, else compute from components
        if "exposure_index" in z and z["exposure_index"] is not None:
            base_ei = float(z["exposure_index"])
        else:
            base_ei = sum(
                float(z.get(component, 0)) * weight
                for component, weight in EXPOSURE_WEIGHTS.items()
            )

        anomaly = float(z.get("current_anomaly_adjustment", 0.0))
        adjusted = base_ei + anomaly

        enriched.append({**z, "adjusted_exposure": adjusted})

    # Normalize so sum of adjusted exposures = 1 (creates valid weight vector)
    total_adjusted = sum(z["adjusted_exposure"] for z in enriched)
    if total_adjusted <= 0:
        raise ValueError("Sum of adjusted_exposure values is zero — cannot normalize.")

    for z in enriched:
        z["normalized_exposure"] = round(z["adjusted_exposure"] / total_adjusted, 6)

    return enriched


# ─────────────────────────────────────────────────────────────────────────────
# Case allocation
# ─────────────────────────────────────────────────────────────────────────────

def allocate_cases_by_scenario(
    zones_enriched: list[dict],
    scenario_cases: int,
) -> dict[str, float]:
    """
    Distribute city-level forecast cases across zones by normalized exposure.

    Returns
    -------
    dict mapping zone_id -> allocated case count (float, un-rounded)
    """
    return {
        z["zone_id"]: z["normalized_exposure"] * scenario_cases
        for z in zones_enriched
    }


# ─────────────────────────────────────────────────────────────────────────────
# SDH calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_sdh(
    current_stock: float,
    baseline_daily_consumption: float,
    growth_factor: float,
) -> float:
    """
    Stock Depletion Horizon (SDH) in days for one consumable item.

    SDH represents how many days the current stock will last given the
    demand level implied by the forecast growth factor.

    dynamic_daily_demand = baseline_daily_consumption * growth_factor
    SDH = current_stock / dynamic_daily_demand

    Uses baseline_daily_consumption * growth_factor rather than a fixed
    demand, because surge volume directly scales diagnostic kit and IV fluid
    throughput. A 1.5x growth factor means ~50% more cases and proportionally
    more consumable use.

    Returns float("inf") when baseline_daily_consumption is zero (no expected
    consumption → stock never depletes under current assumptions).

    Parameters
    ----------
    current_stock : float
        Units currently in stock.
    baseline_daily_consumption : float
        Units used per day under non-surge (baseline) conditions.
    growth_factor : float
        Forecast growth factor (e.g. 1.498 for expected_case).

    Returns
    -------
    float
        Days until depletion. Rounded to 1 decimal place by caller.
    """
    if baseline_daily_consumption <= 0 or growth_factor <= 0:
        return float("inf")
    dynamic_demand = baseline_daily_consumption * growth_factor
    return current_stock / dynamic_demand


# ─────────────────────────────────────────────────────────────────────────────
# Bed load calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_bed_load(
    occupied_dengue_beds: float,
    total_dengue_beds: int,
    allocated_zone_cases: float,
    horizon_days: int,
    avg_length_of_stay: float,
    admission_fraction: float | None = None,
) -> tuple[float, float]:
    """
    Project bed occupancy under a given scenario and compute the bed gap.

    Beds are a cumulative resource held for the duration of each patient's stay.
    Each daily arriving case occupies a bed for avg_length_of_stay days, so
    the ward accumulates concurrent occupancy from multiple cohorts.

    allocated_daily_surge_cases = allocated_zone_cases / horizon_days
    projected_bed_load = occupied_dengue_beds
                       + allocated_daily_surge_cases * avg_length_of_stay
    bed_gap = max(0, projected_bed_load - total_dengue_beds)

    Note: occupied_dengue_beds captures the current concurrent load (patients
    already admitted at the start of the forecast horizon). The projection adds
    the concurrent load from newly arriving surge cases over the horizon.

    Parameters
    ----------
    occupied_dengue_beds : float
        Currently occupied dengue beds.
    total_dengue_beds : int
        Physical dengue bed capacity of this facility.
    allocated_zone_cases : float
        Forecast case count allocated to this zone for the full horizon.
    horizon_days : int
        Forecast horizon in days (14 for 2-week ahead).
    avg_length_of_stay : float
        Mean dengue inpatient stay in days.

    Returns
    -------
    (projected_bed_load, bed_gap) : tuple[float, float]
    """
    if admission_fraction is None:
        admission_fraction = float(get_parameter("OPS.ADMISSION_FRACTION", "admission_fraction"))
    if not 0 <= admission_fraction <= 1:
        raise ValueError("admission_fraction must be within 0 and 1.")
    expected_admissions = allocated_zone_cases * admission_fraction
    daily_admissions = expected_admissions / max(1, horizon_days)
    projected = occupied_dengue_beds + daily_admissions * avg_length_of_stay
    gap = max(0.0, projected - total_dengue_beds)
    return round(projected, 1), round(gap, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Priority score
# ─────────────────────────────────────────────────────────────────────────────

def _priority_category(score: float) -> str:
    for threshold, label in PRIORITY_CATEGORIES:
        if score <= threshold:
            return label
    return "Critical"


def calculate_priority(
    experimental_growth_score: int,
    vulnerability_weight: float,
    exposure_index: float = 0.0,
) -> tuple[int, float, str]:
    """
    Compute the experimental planning-priority score (0–100).

    Governance: this formula is unsupported, benchmark-only, and not an
    official resource-allocation or vector-control priority rule.

    Formula (two components):

      structural = (exposure_index × vulnerability_weight × 200)
                 + (exposure_index × 80)

      forecast_driven = experimental_growth_score × (0.60 + vulnerability_weight × 0.30)

      raw_priority = structural + forecast_driven
      priority_score = min(100, round(raw_priority))

    Rationale:
    ----------
    A pure forecast-multiplied score collapses to near-zero in low-season
    periods (e.g. week 1, winter), making all zones appear identically Routine
    even when structural risk differs significantly. DengueOps AI is a
    *preparedness* decision-support system, not just an outbreak detector — so
    zones with high structural exposure and vulnerability should always carry
    an elevated preparedness score even when case counts are low.

    The structural component captures:
    • Zone loading share (exposure_index): higher exposure → higher baseline
    • Joint vulnerability × exposure: informal settlements with high exposure
      AND high vulnerability get significantly higher structural priority

    The forecast_driven multiplier (0.60 + vulnerability × 0.30) keeps the
    total score below the 100 cap at moderate risk levels, ensuring all five
    zones remain meaningfully differentiated across the full forecast range.

    At low forecast growth (experimental_growth_score ≈ 5), typical outputs:
      Kamrangirchar (exp=0.27, vuln=0.33) → priority ≈ 43  (Moderate)
      Dhanmondi (exp=0.18, vuln=0.13)     → priority ≈ 22  (Routine)

    At moderate forecast growth (experimental_growth_score ≈ 60):
      Kamrangirchar → priority ≈ 81  (Critical)
      Mitford       → priority ≈ 72  (High)
      Jatrabari     → priority ≈ 66  (High)
      Lalbagh       → priority ≈ 65  (High)
      Dhanmondi     → priority ≈ 57  (High)

    At high forecast growth (experimental_growth_score ≈ 82):
      Kamrangirchar → priority ≈ 96  (Critical)
      Dhanmondi     → priority ≈ 71  (High)

    Parameters
    ----------
    experimental_growth_score : int
        Provisional growth score (0–100) from the preparedness scenario.
    vulnerability_weight : float
        Zone-level vulnerability weight from zones.json (e.g. 0.33).
    exposure_index : float
        Zone-level exposure index (0–1, typically 0.15–0.30).

    Returns
    -------
    (priority_score_capped, raw_priority_score, priority_category)
    """
    # Structural preparedness floor — differentiates zones even in low season.
    # Combines zone loading share (exposure_index) with joint vulnerability × exposure.
    structural = (
        exposure_index * vulnerability_weight * float(get_parameter("OPS.PRIORITY.SCORE", "interaction_weight"))
        + exposure_index * float(get_parameter("OPS.PRIORITY.SCORE", "exposure_weight"))
    )

    # Forecast-driven urgency — scaled by 0.6 base + 0.3 × vulnerability.
    # Multiplier kept below 1.0 so that even at Moderate risk (score≈60) the
    # total can land in the High band without always hitting the 100 cap.
    forecast_driven = experimental_growth_score * (
        float(get_parameter("OPS.PRIORITY.SCORE", "growth_base_weight"))
        + vulnerability_weight * float(get_parameter("OPS.PRIORITY.SCORE", "growth_vulnerability_weight"))
    )

    raw = structural + forecast_driven
    capped = min(int(get_parameter("OPS.PRIORITY.SCORE", "score_cap")), round(raw))
    category = _priority_category(capped)
    return capped, round(raw, 2), category


# ─────────────────────────────────────────────────────────────────────────────
# Inventory item classification helper
# ─────────────────────────────────────────────────────────────────────────────

def _is_ns1(item_name: str) -> bool:
    name_lower = item_name.lower()
    return any(kw in name_lower for kw in NS1_KEYWORDS)


def _is_ivf(item_name: str) -> bool:
    name_lower = item_name.lower()
    return any(kw in name_lower for kw in IVF_KEYWORDS)


def _sdh_alert_level(sdh: float, threshold_days: int) -> str:
    """Classify SDH into alert level relative to reorder threshold."""
    if sdh <= float(get_parameter("OPS.STOCK.THRESHOLDS", "critical_days")):
        return "Critical"
    if sdh <= threshold_days:
        return "Warning"
    return "Stable"


def _warning_threshold(item_name: str) -> int:
    parameter = "ns1_warning_days" if _is_ns1(item_name) else "iv_fluid_warning_days"
    return int(get_parameter("OPS.STOCK.THRESHOLDS", parameter))


# ─────────────────────────────────────────────────────────────────────────────
# Inventory alerts
# ─────────────────────────────────────────────────────────────────────────────

def generate_inventory_alerts(
    facility_items: list[dict],
    scenarios: dict,
) -> list[dict]:
    """
    Build structured inventory alert records for all consumable items at a facility.

    Alert levels:
        SDH <= 3 days    → Critical
        SDH <= threshold → Warning
        SDH > threshold  → Stable  (no alert raised, but record still included)

    Only Critical and Warning alerts are returned; Stable items are omitted
    from the alert list to reduce noise.

    Parameters
    ----------
    facility_items : list[dict]
        Inventory items for one facility.
    scenarios : dict
        {"best": (gf, label), "expected": (gf, label), "worst": (gf, label)}

    Returns
    -------
    list[dict]
        Alert records, ordered by alert severity (Critical first).
    """
    alerts: list[dict] = []

    for item in facility_items:
        item_name = item["item_name"]
        stock = float(item["current_stock"])
        baseline = float(item["baseline_daily_consumption"])
        threshold = _warning_threshold(item_name)

        # Compute expected-case SDH for the alert message
        gf_expected = scenarios["expected"][0]
        sdh_expected = calculate_sdh(stock, baseline, gf_expected)
        level = _sdh_alert_level(sdh_expected, threshold)

        if level in ("Critical", "Warning"):
            alerts.append({
                "item_name": item_name,
                "sdh_expected": round(sdh_expected, 1),
                "threshold_days": threshold,
                "alert_level": level,
                "message": (
                    f"{item_name} may deplete in {round(sdh_expected, 1)} days "
                    f"(reorder threshold: {threshold} days)."
                ),
            })

    # Sort: Critical first, then Warning
    alerts.sort(key=lambda a: 0 if a["alert_level"] == "Critical" else 1)
    return alerts


# ─────────────────────────────────────────────────────────────────────────────
# Recommendation generation
# ─────────────────────────────────────────────────────────────────────────────

def generate_recommendations(
    sdh_ns1_expected: float,
    sdh_ns1_threshold: int,
    sdh_ivf_expected: float,
    sdh_ivf_threshold: int,
    bed_gap_expected: float,
    bed_gap_worst: float,
    priority_score: int,
    expected_growth_category: str,
    worst_growth_category: str,
) -> list[str]:
    """
    Generate plain-language operational recommendations for one facility.

    Recommendations are triggered by expected_case thresholds with worst-case
    awareness. This ensures the dashboard communicates the primary operational
    signal without alarming staff on every worst-case scenario, while still
    surfacing contingency needs.

    Rules applied in priority order:
        1. NS1 expected SDH <= reorder threshold → Reorder immediately.
        2. IVF expected SDH <= reorder threshold → Reorder immediately.
        3. Expected bed gap > 0                  → Activate bed protocol.
        4. Worst-case bed gap > 0, expected = 0  → Monitor readiness.
        5. Priority score >= 76                   → Prioritize vector control.
        6. Expected risk High/Critical             → Prepare surge OPD.
        7. Worst-case risk High/Critical           → Contingency plan.
        8. No triggers                             → Routine monitoring.
    """
    recs: list[str] = []

    # Rule 1 — NS1 supply
    if sdh_ns1_expected != float("inf") and sdh_ns1_expected <= sdh_ns1_threshold:
        recs.append("Reorder NS1/RDT kits within 24-48 hours.")

    # Rule 2 — IV fluid supply
    if sdh_ivf_expected != float("inf") and sdh_ivf_expected <= sdh_ivf_threshold:
        recs.append("Reorder IV fluids and prepare dengue supportive care stock.")

    # Rule 3 — Expected bed gap
    if bed_gap_expected > 0:
        recs.append("Activate additional dengue beds or referral protocol.")

    # Rule 4 — Worst-case bed gap only
    if bed_gap_worst > 0 and bed_gap_expected <= 0:
        recs.append("Monitor bed readiness; worst-case scenario may exceed capacity.")

    # Rule 5 — High priority zone
    if priority_score >= float(get_parameter("OPS.DIRECTIVE.TRIGGERS", "priority_trigger")):
        recs.append("Prioritize vector-control response in this zone.")

    # Rule 6 — Expected risk level
    if expected_growth_category in ("High forecast growth", "Very high forecast growth"):
        recs.append("Prepare triage desk and surge OPD workflow.")

    # Rule 7 — Worst-case risk level
    if worst_growth_category in ("High forecast growth", "Very high forecast growth"):
        recs.append("Prepare contingency plan under worst-case forecast.")

    # Rule 8 — No escalation needed
    if not recs:
        recs.append("Routine monitoring; no immediate operational escalation required.")

    return recs


# ─────────────────────────────────────────────────────────────────────────────
# Core directive builder
# ─────────────────────────────────────────────────────────────────────────────

def build_directives(
    forecast: dict,
    zones: list[dict],
    facilities: list[dict],
    inventory: list[dict],
    deployment_gate: str | None = None,
) -> dict:
    """
    Orchestrate all calculations and assemble the full directives output.

    Parameters
    ----------
    forecast : dict
        forecast_output.json content (must include authoritative preparedness_scenarios).
    zones : list[dict]
        zones.json content.
    facilities : list[dict]
        facilities.json content.
    inventory : list[dict]
        inventory.json content.

    Returns
    -------
    dict
        Complete directives structure matching the data contract.
    """
    # ── Extract scenario parameters ───────────────────────────────────────────
    deployment_gate = deployment_gate or current_deployment_gate()
    assert_formulas_allowed(OPERATIONAL_FORMULA_IDS, deployment_gate)
    scenarios_raw = forecast.get("preparedness_scenarios", {})
    if not scenarios_raw:
        raise ValueError(
            "forecast_output.json is missing authoritative preparedness_scenarios; "
            "the deprecated uncertainty_scenarios alias cannot drive operations."
        )
    if forecast.get("uncertainty_scenarios") != scenarios_raw:
        raise ValueError("Deprecated uncertainty_scenarios alias differs from authoritative preparedness_scenarios.")
    if forecast.get("forecast_uncertainty", {}).get("is_prediction_interval") is not False:
        raise ValueError("Operational input must preserve the non-prediction-interval P1.3 status.")

    best_cases     = int(scenarios_raw["best_case"]["forecast_cases"])
    expected_cases = int(scenarios_raw["expected_case"]["forecast_cases"])
    worst_cases    = int(scenarios_raw["worst_case"]["forecast_cases"])

    gf_best     = float(scenarios_raw["best_case"]["growth_factor"])
    gf_expected = float(scenarios_raw["expected_case"]["growth_factor"])
    gf_worst    = float(scenarios_raw["worst_case"]["growth_factor"])

    score_expected = int(scenarios_raw["expected_case"]["experimental_growth_score"])
    category_expected = scenarios_raw["expected_case"]["forecast_growth_category"]
    category_worst = scenarios_raw["worst_case"]["forecast_growth_category"]

    horizon_days = int(forecast.get("horizon_days", 14))

    # ── Compute exposure weights ──────────────────────────────────────────────
    zones_enriched = compute_exposure_weights(zones)

    # ── Allocate cases per zone for each scenario ─────────────────────────────
    alloc_best     = allocate_cases_by_scenario(zones_enriched, best_cases)
    alloc_expected = allocate_cases_by_scenario(zones_enriched, expected_cases)
    alloc_worst    = allocate_cases_by_scenario(zones_enriched, worst_cases)

    # ── Index lookups ─────────────────────────────────────────────────────────
    # Support multiple facilities per zone
    facilities_by_zone: dict[str, list[dict]] = {}
    for f in facilities:
        facilities_by_zone.setdefault(f["zone_id"], []).append(f)

    inventory_by_facility: dict[str, list[dict]] = {}
    for item in inventory:
        fid = item["facility_id"]
        inventory_by_facility.setdefault(fid, []).append(item)

    # ── Build one directive per facility (multiple per zone) ──────────────────
    directives: list[dict] = []
    now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    def _sdh_triple(items: list[dict]) -> tuple[float, float, float]:
        """Return (sdh_best, sdh_expected, sdh_worst) for the first matching item."""
        if not items:
            return float("inf"), float("inf"), float("inf")
        item = items[0]
        stock    = float(item["current_stock"])
        baseline = float(item["baseline_daily_consumption"])
        return (
            calculate_sdh(stock, baseline, gf_best),
            calculate_sdh(stock, baseline, gf_expected),
            calculate_sdh(stock, baseline, gf_worst),
        )

    for zone in zones_enriched:
        zid = zone["zone_id"]
        zone_facilities = facilities_by_zone.get(zid, [])
        if not zone_facilities:
            continue

        # ── Zone-level allocation (shared across all facilities in zone) ──────
        zone_ac_best     = alloc_best[zid]
        zone_ac_expected = alloc_expected[zid]
        zone_ac_worst    = alloc_worst[zid]

        # ── Priority is zone-level (same for all facilities in zone) ─────────
        vuln  = float(zone.get("vulnerability_weight", 0.0))
        expo  = float(zone.get("exposure_index", 0.0))
        priority_capped, priority_raw, priority_category = calculate_priority(
            score_expected, vuln, exposure_index=expo
        )

        # ── Facility load shares within this zone ─────────────────────────────
        # Based on baseline_daily_dengue_cases: larger facilities absorb more
        # of the zone's allocated case surge proportionally.
        zone_total_baseline = sum(
            float(f.get("baseline_daily_dengue_cases_demo", f.get("baseline_daily_dengue_cases", 1)))
            for f in zone_facilities
        )

        for facility in zone_facilities:
            fid = facility["facility_id"]
            fac_items = inventory_by_facility.get(fid, [])

            # ── Facility load share ───────────────────────────────────────────
            f_baseline = float(facility.get("baseline_daily_dengue_cases_demo",
                                            facility.get("baseline_daily_dengue_cases", 1)))
            if zone_total_baseline > 0:
                f_load_share = f_baseline / zone_total_baseline
            else:
                f_load_share = 1.0 / len(zone_facilities)

            # ── Facility-level allocated cases ────────────────────────────────
            # facility_allocated_cases = zone_allocated_cases × facility_load_share
            fac_ac_best     = zone_ac_best     * f_load_share
            fac_ac_expected = zone_ac_expected * f_load_share
            fac_ac_worst    = zone_ac_worst    * f_load_share

            # ── Bed load per scenario (per facility) ──────────────────────────
            # Support both old field names (placeholder) and new schema names
            occ = float(facility.get("occupied_dengue_beds_demo",
                                     facility.get("occupied_dengue_beds", 0)))
            cap = int(facility.get("dengue_bed_capacity_demo",
                                   facility.get("total_dengue_beds", 10)))
            los = float(facility["avg_length_of_stay"])

            pbl_best,  bg_best  = calculate_bed_load(occ, cap, fac_ac_best,     horizon_days, los)
            pbl_exp,   bg_exp   = calculate_bed_load(occ, cap, fac_ac_expected, horizon_days, los)
            pbl_worst, bg_worst = calculate_bed_load(occ, cap, fac_ac_worst,    horizon_days, los)

            # ── SDH per scenario — NS1 and IV Fluid ───────────────────────────
            ns1_items = [i for i in fac_items if _is_ns1(i["item_name"])]
            ivf_items = [i for i in fac_items if _is_ivf(i["item_name"]) and not _is_ns1(i["item_name"])]

            sdh_ns1_best, sdh_ns1_exp, sdh_ns1_worst = _sdh_triple(ns1_items)
            sdh_ivf_best, sdh_ivf_exp, sdh_ivf_worst = _sdh_triple(ivf_items)

            ns1_threshold = int(get_parameter("OPS.STOCK.THRESHOLDS", "ns1_warning_days"))
            ivf_threshold = int(get_parameter("OPS.STOCK.THRESHOLDS", "iv_fluid_warning_days"))

            # ── Inventory alerts (expected-case based) ────────────────────────
            scenario_gfs = {
                "best":     (gf_best,     "best_case"),
                "expected": (gf_expected, "expected_case"),
                "worst":    (gf_worst,    "worst_case"),
            }
            inv_alerts = generate_inventory_alerts(fac_items, scenario_gfs)

            # ── Recommendations ───────────────────────────────────────────────
            recs = generate_recommendations(
                sdh_ns1_expected=sdh_ns1_exp,
                sdh_ns1_threshold=ns1_threshold,
                sdh_ivf_expected=sdh_ivf_exp,
                sdh_ivf_threshold=ivf_threshold,
                bed_gap_expected=bg_exp,
                bed_gap_worst=bg_worst,
                priority_score=priority_capped,
                expected_growth_category=category_expected,
                worst_growth_category=category_worst,
            )
            planning_suggestions = [
                {
                    "label": suggestion,
                    "type": "Simulated planning suggestion",
                    "formula_ids": ["OPS.DIRECTIVE.TRIGGERS"],
                    "deployment_gate": "benchmark_only",
                    "approval_status": "not_approved",
                    "disclaimer": "Prototype trigger condition only; not an operational recommendation.",
                }
                for suggestion in recs
            ]

            # ── Assemble directive record ─────────────────────────────────────
            directives.append({
                "forecast_id":         int(forecast.get("forecast_id", 1)),
                "target_epi_year":     int(forecast.get("target_epi_year", 2026)),
                "target_epi_week":     int(forecast.get("target_epi_week", 24)),
                "zone_id":             zid,
                "zone_name":           zone["zone_name"],
                "zone_profile":        zone.get("profile", ""),
                "facility_id":         fid,
                "facility_name":       facility["facility_name"],
                "facility_type":       facility.get("facility_type", ""),
                "facility_anchor_type": facility.get("facility_anchor_type", ""),
                "data_status":         facility.get("data_status", "synthetic_readiness_profile"),
                "exposure_index":      round(float(zone["exposure_index"]), 4),
                "adjusted_exposure":   round(float(zone["adjusted_exposure"]), 4),
                "normalized_exposure": round(float(zone["normalized_exposure"]), 6),
                # ─ Facility load share within zone ─
                "facility_load_share":          round(f_load_share, 4),
                # ─ Facility-level case allocations ─
                "allocated_cases_best":         round(fac_ac_best, 1),
                "allocated_cases_expected":     round(fac_ac_expected, 1),
                "allocated_cases_worst":        round(fac_ac_worst, 1),
                # ─ Zone-level case totals (for reference) ─
                "zone_allocated_cases_best":    round(zone_ac_best, 1),
                "zone_allocated_cases_expected": round(zone_ac_expected, 1),
                "zone_allocated_cases_worst":   round(zone_ac_worst, 1),
                # ─ Priority (zone-level, shared across zone facilities) ─
                "priority_score":       priority_capped,
                "raw_priority_score":   priority_raw,
                "priority_category":    priority_category,
                "planning_priority_tier": PLANNING_TIER_LABELS[priority_category],
                "planning_priority_label": "Experimental planning-priority score",
                # ─ Bed load (facility-level) ─
                "projected_bed_load_best":     pbl_best,
                "projected_bed_load_expected": pbl_exp,
                "projected_bed_load_worst":    pbl_worst,
                "bed_gap_best":                bg_best,
                "bed_gap_expected":            bg_exp,
                "bed_gap_worst":               bg_worst,
                "general_bed_capacity":        facility.get("general_bed_capacity"),
                "dengue_bed_capacity_demo":    cap,
                "occupied_dengue_beds_demo":   int(occ),
                "avg_length_of_stay":          los,
                "admission_fraction": float(get_parameter("OPS.ADMISSION_FRACTION", "admission_fraction")),
                "bed_demand_label": "Illustrative bed-demand estimate using provisional admission and LOS parameters",
                # ─ SDH consumables (facility-level) ─
                "sdh_ns1_best":     round(sdh_ns1_best,  1) if sdh_ns1_best  != float("inf") else None,
                "sdh_ns1_expected": round(sdh_ns1_exp,   1) if sdh_ns1_exp   != float("inf") else None,
                "sdh_ns1_worst":    round(sdh_ns1_worst, 1) if sdh_ns1_worst != float("inf") else None,
                "sdh_iv_fluid_best":     round(sdh_ivf_best,  1) if sdh_ivf_best  != float("inf") else None,
                "sdh_iv_fluid_expected": round(sdh_ivf_exp,   1) if sdh_ivf_exp   != float("inf") else None,
                "sdh_iv_fluid_worst":    round(sdh_ivf_worst, 1) if sdh_ivf_worst != float("inf") else None,
                # ─ Alerts and recommendations ─
                "inventory_alerts":     inv_alerts,
                # TD-P03A-LEGACY-RISK-FIELDS: compatibility only; use planning_suggestions.
                "planning_suggestions": planning_suggestions,
                "generation_timestamp": now_ts,
            })

    # ── Summary block ─────────────────────────────────────────────────────────
    total_fac      = len(directives)
    pub_gov_count  = sum(1 for d in directives if d.get("facility_anchor_type") == "real_public_hospital_anchor")
    # Critical priority zones: count unique zones with Critical priority
    critical_zones = len({d["zone_id"] for d in directives if d["priority_category"] == "Critical"})
    exp_bed_gaps   = sum(1 for d in directives if d["bed_gap_expected"] > 0)
    worst_bed_gaps = sum(1 for d in directives if d["bed_gap_worst"] > 0)
    critical_alerts = sum(
        1 for d in directives
        for a in d["inventory_alerts"]
        if a["alert_level"] == "Critical"
    )
    # highest_priority_zone: zone with highest raw_priority_score
    highest_priority_zone = max(directives, key=lambda d: d["raw_priority_score"])["zone_name"]
    # highest_pressure_facility: facility with largest expected bed gap
    highest_pressure_facility = max(directives, key=lambda d: d["bed_gap_expected"])["facility_name"]

    total_planning_suggestions = sum(len(d["planning_suggestions"]) for d in directives)

    summary = {
        "total_facilities":                   total_fac,
        "total_public_government_anchors":    pub_gov_count,
        "critical_priority_zones":            critical_zones,
        "facilities_with_expected_bed_gap":   exp_bed_gaps,
        "facilities_with_worst_case_bed_gap": worst_bed_gaps,
        "critical_supply_alerts":             critical_alerts,
        "highest_priority_zone":              highest_priority_zone,
        "highest_pressure_facility":          highest_pressure_facility,
        "total_planning_suggestions":         total_planning_suggestions,
    }

    # ── Wrap into final output dict ───────────────────────────────────────────
    output = {
        "provenance": forecast.get("provenance"),
        "generated_at":  now_ts,
        "forecast_id":   int(forecast.get("forecast_id", 1)),
        "target_epi_year": int(forecast.get("target_epi_year", 2026)),
        "target_epi_week": int(forecast.get("target_epi_week", 24)),
        "horizon_days":  horizon_days,
        "city":          str(forecast.get("city", "Dhaka South")),
        "allocation_method": {
            "type": "spatial_exposure_index",
            "components": EXPOSURE_WEIGHTS,
            "note": (
                "Prototype spatial exposure allocation under city-level data constraints. "
                "Exposure index is derived from population share, density, facility pressure, "
                "and mobility corridor weights. Anomaly adjustment is additive and "
                "reflects current-week deviations (e.g. flooding, outbreak reports)."
            ),
        },
        "scenario_context": {
            "best_case":     scenarios_raw["best_case"],
            "expected_case": scenarios_raw["expected_case"],
            "worst_case":    scenarios_raw["worst_case"],
        },
        "scenario_policy": {
            "authoritative_source": "forecast_output.json#preparedness_scenarios",
            "method": "legacy_rf_rmse_planning_sensitivity",
            "forecast_empirical_range_drives_directives": False,
            "separation_status": "planning_scenarios_separate_from_forecast_uncertainty",
        },
        "directives": directives,
        "summary":    summary,
        "notes": [
            "Facility and inventory data are synthetic/demo for prototype demonstration.",
            "Facility identity and readiness status are source-specific. Synthetic benchmark "
            "facilities are wholly synthetic; synthetic demo readiness values do not represent actual records.",
            "Outputs are simulated planning suggestions, not operational recommendations.",
            "Spatial case allocation is a heuristic under sub-city data constraints; "
            "zone-level counts are not precision estimates.",
            "Facility-level cases are allocated within a zone using baseline_daily_dengue_cases "
            "load shares — larger facilities absorb a proportionally larger share of zone surge.",
            "Planning sensitivity scenarios use legacy RF holdout RMSE for operational compatibility and are separate from forecast uncertainty.",
            "Bed gap and SDH calculations assume steady-state surge over the 14-day horizon.",
        ],
    }
    formula_ids = list(forecast.get("formula_ids_used", [])) + list(OPERATIONAL_FORMULA_IDS)
    output.update(build_formula_metadata(formula_ids, deployment_gate))
    output["operational_status"] = "synthetic_prototype_not_approved"
    output["suggestion_label"] = "Simulated planning suggestion"
    output["non_operational_disclaimer"] = (
        "Prototype trigger conditions only; institutional approval is required before operational use."
    )
    return output


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print("=" * 66)
    print("  DengueOps AI - Phase 5: Operational Decision-Support Engine")
    print("=" * 66)

    # ── Load all inputs ───────────────────────────────────────────────────────
    print("\n  Loading input files...")
    forecast   = load_json(FORECAST_PATH)
    artifact_provenance(forecast, "forecast_output.json")
    zones      = load_json(ZONES_PATH)
    facilities = load_json(FACILITIES_PATH)
    inventory  = load_json(INVENTORY_PATH)

    scenarios  = forecast.get("preparedness_scenarios", {})
    print(f"    Zones: {len(zones)}  |  Facilities: {len(facilities)}  "
          f"|  Inventory items: {len(inventory)}")
    print(f"    Scenarios: best={scenarios['best_case']['forecast_cases']}, "
          f"expected={scenarios['expected_case']['forecast_cases']}, "
          f"worst={scenarios['worst_case']['forecast_cases']} cases")

    # ── Build directives ──────────────────────────────────────────────────────
    print("\n  Running operational engine...")
    try:
        output = build_directives(forecast, zones, facilities, inventory)
    except FormulaRegistryError as exc:
        print(f"\n  [FORMULA GATE BLOCKED] {exc}")
        return 2

    # ── Print summary ─────────────────────────────────────────────────────────
    s = output["summary"]
    print()
    print(f"  {'-'*66}")
    print(f"  Summary (expected scenario):")
    print(f"    Total facilities          : {s['total_facilities']}")
    print(f"    Public/govt anchors       : {s['total_public_government_anchors']}")
    print(f"    Highest priority zone     : {s['highest_priority_zone']}")
    print(f"    Highest pressure facility : {s['highest_pressure_facility'][:40]}")
    print(f"    Critical priority zones   : {s['critical_priority_zones']}")
    print(f"    Bed gaps (expected)       : {s['facilities_with_expected_bed_gap']} facilities")
    print(f"    Bed gaps (worst case)     : {s['facilities_with_worst_case_bed_gap']} facilities")
    print(f"    Critical supply alerts    : {s['critical_supply_alerts']}")
    print(f"    Total planning suggestions: {s['total_planning_suggestions']}")
    print(f"  {'-'*66}")

    print()
    header = f"  {'Facility':<40}  {'Zone':<22}  {'PriCat':<10}  {'BedGap(exp)':>11}  {'NS1 SDH':>8}"
    print(header)
    print(f"  {'-'*100}")
    for d in output["directives"]:
        anchor_flag = " [pub]" if d.get("facility_anchor_type") == "public_government" else ""
        fac_label = (d["facility_name"][:34] + anchor_flag)[:40]
        print(
            f"  {fac_label:<40}  {d['zone_name']:<22}  "
            f"{d['priority_category']:<10}  "
            f"{d['bed_gap_expected']:>11.1f}  "
            f"{(str(d['sdh_ns1_expected']) + 'd') if d['sdh_ns1_expected'] else 'N/A':>8}"
        )

    # ── Save ──────────────────────────────────────────────────────────────────
    save_json(DIRECTIVES_PATH, output)
    print(f"\n  Saved: {DIRECTIVES_PATH}")

    print()
    print("=" * 66)
    print("  Operational engine complete.")
    print("=" * 66)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
