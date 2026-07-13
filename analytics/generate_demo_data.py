"""
generate_demo_data.py
=====================
DengueOps AI — Phase 1: Realistic Synthetic Demo Data Generation

Generates all data files required by the DengueOps AI prototype:
    - data/dengue_cases.csv      Weekly dengue case counts (Dhaka South, 2024–2026)
    - data/climate_data.csv      Weekly climate variables (same period)
    - data/zones.json            Five operational zones with exposure indices
    - data/facilities.json       11 health facilities across 5 zones (multiple per zone)
    - data/inventory.json        NS1/RDT kit and IV fluid stock per facility (22 items)

Facility naming note:
    Real public/government facility names (e.g. Dhaka Medical College Hospital,
    Sir Salimullah Medical College & Mitford Hospital, Mugda Medical College Hospital)
    are used ONLY as public-sector anchor profiles — i.e., location and capacity-class
    reference points. All bed counts, occupancy levels, stock values, consumption
    rates, and readiness values are SYNTHETIC and do not represent actual facility
    records, current stock levels, or real operational capacity.
    Each facility record includes data_status="synthetic_readiness_profile" and
    facility_anchor_type to make this explicit.

Ethics statement:
    All records are SYNTHETIC DEMO DATA only.
    No patient-level, individual-level, or de-identified personal health data is
    generated, used, or represented. All values are simulated from epidemiologically
    motivated parameters for prototype demonstration purposes only.

Usage:
    python analytics/generate_demo_data.py

    Safe to run multiple times — overwrites existing demo files.

Requirements:
    Python 3.10+, pandas, numpy (standard; no additional installs needed if
    requirements.txt is installed)
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# ── Reproducibility ───────────────────────────────────────────────────────────
RANDOM_SEED = 42
rng = np.random.default_rng(RANDOM_SEED)

# ── Output paths ─────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DHAKA_SOUTH_GEOGRAPHY_ID = "BGD-DHAKA-SOUTH"
DHAKA_SOUTH_LATITUDE = 23.7104
DHAKA_SOUTH_LONGITUDE = 90.4074

# ── Date helpers ─────────────────────────────────────────────────────────────

def epi_week_start(year: int, week: int) -> date:
    """
    Return the Monday of CDC epi week (week 1 = first week containing Jan 4).
    Simplified: treat epi week 1 as the first Monday of the year or Jan 1 itself.
    We use ISO week numbering here for reproducibility.
    """
    # ISO week 1 is the week containing the first Thursday of the year.
    # We approximate epi week ≈ ISO week for demo purposes.
    jan4 = date(year, 1, 4)
    # Monday of the ISO week containing Jan 4 = week 1 start
    week1_start = jan4 - timedelta(days=jan4.weekday())
    return week1_start + timedelta(weeks=week - 1)


# ─────────────────────────────────────────────────────────────────────────────
# 1. DENGUE CASES
# ─────────────────────────────────────────────────────────────────────────────

# Dengue seasonal parameters for Dhaka / Bangladesh
# Peak occurs around epi weeks 38–45 (September–November).
# Monsoon rainfall lags ~4 weeks before driving case increases.
# Dry/low-transmission period: weeks 1–18 (January–May).

DENGUE_PEAK_WEEK = 42        # peak epi week in surge season
DENGUE_SEASON_WIDTH = 14     # half-width of surge season (weeks)
DENGUE_TROUGH = 55           # minimum weekly cases (dry season)
DENGUE_PEAK_2024 = 920       # peak weekly cases, 2024
DENGUE_PEAK_2025 = 1380      # stronger 2025 surge
DENGUE_PEAK_2026 = 640       # 2026 partial year — early warning rising pattern

# Inter-year variation multipliers applied to noise
NOISE_SCALE = 0.11


def dengue_seasonal_baseline(week: int, peak_cases: float, trough: float = DENGUE_TROUGH) -> float:
    """
    Asymmetric seasonal baseline for dengue cases.
    Uses a Gaussian bell curve centred at DENGUE_PEAK_WEEK.
    Rises faster than it falls (post-monsoon rise is sharp; decline is slower).
    """
    # Asymmetric width: pre-peak narrower, post-peak wider
    if week <= DENGUE_PEAK_WEEK:
        sigma = DENGUE_SEASON_WIDTH * 0.85
    else:
        sigma = DENGUE_SEASON_WIDTH * 1.25

    gaussian = math.exp(-0.5 * ((week - DENGUE_PEAK_WEEK) / sigma) ** 2)
    return trough + (peak_cases - trough) * gaussian


def generate_dengue_cases() -> pd.DataFrame:
    """
    Generate weekly dengue case counts for Dhaka South, 2024–2026 (up to week 24).

    Epidemiological basis:
    - Seasonal pattern: low Jan–May, rising June–August, peak Sep–Nov, declining Dec.
    - 2025 has a stronger surge (~50% higher peak) than 2024.
    - 2026 shows an early-warning rising pattern; by week 24 cases are elevated
      but have not yet reached the full surge peak (monsoon just starting).
    - Deaths are proportional to cases with a very low case-fatality ratio (~0.4–0.6%).
    - Noise is multiplicative to preserve non-negativity.
    """
    rows = []

    periods = [
        (2024, range(1, 53)),
        (2025, range(1, 53)),
        (2026, range(1, 25)),   # up to week 24 only
    ]

    peak_map = {
        2024: DENGUE_PEAK_2024,
        2025: DENGUE_PEAK_2025,
        2026: DENGUE_PEAK_2026,
    }

    # 2026 also has a slight seasonal upward shift (climate drift)
    peak_week_shift = {2024: 0, 2025: 1, 2026: 0}

    for year, weeks in periods:
        peak = peak_map[year]
        shift = peak_week_shift[year]

        # Pre-compute year-level random multiplier for inter-year variability
        year_factor = float(rng.normal(1.0, 0.04))   # ±4% year-level variation

        for week in weeks:
            adjusted_week = week - shift
            baseline = dengue_seasonal_baseline(adjusted_week, peak) * year_factor

            # Multiplicative noise: log-normal to keep values positive and skewed right
            noise_factor = float(rng.lognormal(mean=0.0, sigma=NOISE_SCALE))
            cases = max(0, round(baseline * noise_factor))

            # 2026: add slight early-season upward pressure (wetter early monsoon)
            if year == 2026 and week >= 18:
                early_pressure = 1.0 + (week - 17) * 0.022   # +2.2% per week from week 18
                cases = round(cases * early_pressure)

            # Deaths: Poisson draw from CFR of ~0.5%, minimum 0 at low case counts
            cfr = rng.uniform(0.003, 0.006)          # case-fatality rate 0.3–0.6%
            expected_deaths = cases * cfr
            deaths = int(rng.poisson(max(0, expected_deaths)))
            deaths = min(deaths, max(0, cases // 50))   # hard cap: never > 2% of cases

            rows.append({
                "epi_year": year,
                "epi_week": week,
                "date_start": epi_week_start(year, week).isoformat(),
                "geography_level": "city",
                "geography_id": DHAKA_SOUTH_GEOGRAPHY_ID,
                "geography_name": "Dhaka South",
                "city": "Dhaka South",
                "cases": cases,
                "deaths": deaths,
                "deaths_data_status": "observed_or_simulated",
                "source_type": "synthetic_demo",
                "is_approximated": False,
                "approximation_method": None,
            })

    df = pd.DataFrame(rows)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 2. CLIMATE DATA
# ─────────────────────────────────────────────────────────────────────────────

# Dhaka seasonal climate parameters
# Monsoon: weeks ~22–38 (June–September) — high rainfall, high humidity
# Dry/cool: weeks ~46–8  (Nov–Feb)       — low rainfall, lower humidity
# Hot/pre-monsoon: weeks ~9–21           — rising temp, low rainfall
# Post-monsoon: weeks ~39–45             — declining rain, still humid

MONSOON_PEAK_WEEK = 30          # week of peak rainfall (late July)
MONSOON_WIDTH = 8               # half-width of monsoon rainfall bell curve
RAIN_PEAK_MM = 68               # peak weekly rainfall at monsoon centre (mm)
RAIN_DRY_MM = 3                 # dry season weekly rainfall floor (mm)

TEMP_PEAK_WEEK = 26             # hottest week (late June)
TEMP_MIN_C = 18.5               # coldest week average (January)
TEMP_MAX_C = 34.2               # hottest week average (June)

HUM_PEAK_WEEK = 32              # peak humidity week
HUM_MIN_PCT = 58                # minimum humidity (dry season)
HUM_MAX_PCT = 91                # maximum humidity (monsoon)


def climate_seasonal(
    week: int,
    peak_week: float,
    min_val: float,
    max_val: float,
    width: float = 10,
    asymmetric: bool = False,
) -> float:
    """Gaussian bell curve seasonal model for climate variables."""
    sigma = width
    gaussian = math.exp(-0.5 * ((week - peak_week) / sigma) ** 2)
    return min_val + (max_val - min_val) * gaussian


def rainfall_weekly(week: int) -> float:
    """
    Rainfall uses a broader Gaussian centred on monsoon peak (week 30).
    Pre-monsoon and post-monsoon tails add smaller secondary contributions.
    """
    # Main monsoon peak
    main = climate_seasonal(week, MONSOON_PEAK_WEEK, RAIN_DRY_MM, RAIN_PEAK_MM, width=8)
    # Pre-monsoon shower contribution (week 18–22)
    pre = climate_seasonal(week, 19, 0, 12, width=3)
    # Post-monsoon residual (week 38–44)
    post = climate_seasonal(week, 41, 0, 8, width=3)
    return max(RAIN_DRY_MM, main + pre + post)


def temperature_weekly(week: int) -> float:
    """
    Temperature follows a slightly asymmetric seasonal curve.
    Dhaka cools quickly after October (northern front), warms slowly in spring.
    """
    return climate_seasonal(week, TEMP_PEAK_WEEK, TEMP_MIN_C, TEMP_MAX_C, width=16)


def humidity_weekly(week: int) -> float:
    """
    Humidity closely follows the rainfall pattern but with a wider spread.
    Stays elevated for ~2 weeks after peak rainfall.
    """
    return climate_seasonal(week, HUM_PEAK_WEEK, HUM_MIN_PCT, HUM_MAX_PCT, width=10)


def generate_climate_data() -> pd.DataFrame:
    """
    Generate weekly climate data for Dhaka South, 2024–2026 (up to week 24).

    Year-to-year variation:
    - 2025: slightly drier pre-monsoon but more intense peak rainfall
    - 2026: early-onset monsoon (week 20 instead of 22) — consistent with
      the early dengue pressure pattern in the case data
    """
    rows = []

    periods = [
        (2024, range(1, 53)),
        (2025, range(1, 53)),
        (2026, range(1, 25)),
    ]

    # Year-level perturbations for climate variability
    year_rain_scale   = {2024: 1.00, 2025: 1.08, 2026: 1.14}  # 2026 wetter
    year_temp_offset  = {2024: 0.0,  2025: 0.3,  2026: 0.5}   # slight warming trend
    year_monsoon_shift = {2024: 0, 2025: 0, 2026: -2}          # 2026 early monsoon

    for year, weeks in periods:
        r_scale      = year_rain_scale[year]
        temp_offset  = year_temp_offset[year]
        m_shift      = year_monsoon_shift[year]

        for week in weeks:
            adj_week = week - m_shift   # shift monsoon timing

            # Base values
            rain_base = rainfall_weekly(adj_week) * r_scale  # type: ignore[operator]
            temp_base = temperature_weekly(week) + temp_offset
            hum_base = humidity_weekly(adj_week)

            # Additive Gaussian noise for each variable
            rain = max(0.0, round(rain_base + float(rng.normal(0, rain_base * 0.18)), 1))
            temp = round(temp_base + float(rng.normal(0, 0.7)), 1)
            temp = max(15.0, min(38.0, temp))   # physical bounds
            hum = round(hum_base + float(rng.normal(0, 3.5)), 1)
            hum = max(40.0, min(98.0, hum))

            rows.append({
                "epi_year": year,
                "epi_week": week,
                "date_start": epi_week_start(year, week).isoformat(),
                "geography_level": "city",
                "geography_id": DHAKA_SOUTH_GEOGRAPHY_ID,
                "geography_name": "Dhaka South",
                "latitude": DHAKA_SOUTH_LATITUDE,
                "longitude": DHAKA_SOUTH_LONGITUDE,
                "rainfall_mm": rain,
                "avg_temp_c": temp,
                "humidity_pct": hum,
                "coverage_days": 7,
                "source_type": "synthetic_demo",
                "aggregation_method": "simulated_weekly",
                "is_approximated": False,
            })

    df = pd.DataFrame(rows)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 3. ZONES
# ─────────────────────────────────────────────────────────────────────────────

# Exposure index formula (from Phase 0 specification):
#   exposure_index = population_share * 0.40
#                  + density_weight   * 0.30
#                  + facility_pressure_weight * 0.20
#                  + mobility_corridor_weight * 0.10
#
# Then multiplied by current_anomaly_adjustment for operational tuning.

def compute_exposure_index(
    population_share: float,
    density_weight: float,
    facility_pressure_weight: float,
    mobility_corridor_weight: float,
    current_anomaly_adjustment: float,
) -> float:
    raw = (
        population_share * 0.40
        + density_weight * 0.30
        + facility_pressure_weight * 0.20
        + mobility_corridor_weight * 0.10
    )
    return round(raw * current_anomaly_adjustment, 4)


def generate_zones() -> list[dict]:
    """
    Generate five operational zone definitions for Dhaka South.

    Zone profiles are calibrated so that:
    - Kamrangirchar: highest vulnerability (dense informal settlement)
    - Mitford / Old Dhaka: high facility pressure (major hospital nearby)
    - Jatrabari / Sayedabad: highest mobility corridor weight (transport hub)
    - Dhanmondi: lowest vulnerability (mixed residential-institutional)
    - Lalbagh / Hazaribagh: moderate across all dimensions (industrial-residential)
    """

    raw_zones = [
        {
            "zone_id": "Z01",
            "zone_name": "Kamrangirchar",
            "city": "Dhaka South",
            # Large population share; highest density (informal settlement)
            "population_share": 0.22,
            "density_weight": 0.28,
            "facility_pressure_weight": 0.24,
            "mobility_corridor_weight": 0.17,
            "vulnerability_weight": 0.33,       # Highest vulnerability
            "current_anomaly_adjustment": 1.12,  # Recent case anomaly detected
            "profile": "High-density informal settlement",
        },
        {
            "zone_id": "Z02",
            "zone_name": "Mitford / Old Dhaka",
            "city": "Dhaka South",
            # Dense commercial zone; high facility pressure from SSMC hospital
            "population_share": 0.19,
            "density_weight": 0.24,
            "facility_pressure_weight": 0.31,   # Highest facility pressure
            "mobility_corridor_weight": 0.26,
            "vulnerability_weight": 0.22,
            "current_anomaly_adjustment": 1.08,
            "profile": "Dense commercial-residential with major hospital",
        },
        {
            "zone_id": "Z03",
            "zone_name": "Dhanmondi",
            "city": "Dhaka South",
            # Mixed residential-institutional; lower vulnerability
            "population_share": 0.18,
            "density_weight": 0.17,
            "facility_pressure_weight": 0.20,
            "mobility_corridor_weight": 0.22,
            "vulnerability_weight": 0.13,       # Lowest vulnerability
            "current_anomaly_adjustment": 0.97,  # Slightly below average anomaly
            "profile": "Mixed residential-institutional",
        },
        {
            "zone_id": "Z04",
            "zone_name": "Jatrabari / Sayedabad",
            "city": "Dhaka South",
            # Major bus/transport terminus; highest mobility
            "population_share": 0.21,
            "density_weight": 0.22,
            "facility_pressure_weight": 0.15,
            "mobility_corridor_weight": 0.29,   # Highest mobility corridor weight
            "vulnerability_weight": 0.20,
            "current_anomaly_adjustment": 1.05,
            "profile": "High-density transport hub",
        },
        {
            "zone_id": "Z05",
            "zone_name": "Lalbagh / Hazaribagh",
            "city": "Dhaka South",
            # Industrial (tanneries) + dense residential
            "population_share": 0.20,
            "density_weight": 0.21,
            "facility_pressure_weight": 0.22,
            "mobility_corridor_weight": 0.18,
            "vulnerability_weight": 0.20,
            "current_anomaly_adjustment": 1.02,
            "profile": "Dense industrial-residential",
        },
    ]

    # Compute exposure index for each zone
    for z in raw_zones:
        z["exposure_index"] = compute_exposure_index(
            z["population_share"],
            z["density_weight"],
            z["facility_pressure_weight"],
            z["mobility_corridor_weight"],
            z["current_anomaly_adjustment"],
        )

    return raw_zones


# ─────────────────────────────────────────────────────────────────────────────
# 4. FACILITIES
# ─────────────────────────────────────────────────────────────────────────────

def generate_facilities() -> list[dict]:
    """
    Generate 11 health facilities across 5 zones.

    Facility anchor types:
      "real_public_hospital_anchor"   — real government/public facility name used
                                        as a credible location and capacity-class
                                        anchor. general_bed_capacity drawn from
                                        publicly available/official references.
      "synthetic_local_response_unit" — a synthetic local profile representing a
                                        health post or triage unit in that zone.

    Field conventions:
      general_bed_capacity       — Total general bed count for real anchors (public
                                   reference); synthetic assumption for local units.
      dengue_bed_capacity_demo   — Smaller synthetic subset used ONLY for the dengue
                                   preparedness simulation. Does NOT claim to represent
                                   actual designated dengue wards.
      occupied_dengue_beds_demo  — Synthetic demo occupancy; must be <=
                                   dengue_bed_capacity_demo.
      baseline_daily_dengue_cases_demo — Synthetic daily throughput figure used for
                                   facility load-share allocation within a zone.
      bed_capacity_source        — "public_reference_anchor" for real hospitals,
                                   "synthetic_demo_assumption" for synthetic units.
      readiness_data_status      — Always "synthetic_operational_readiness".
      inventory_data_status      — Always "synthetic_inventory_demo".

    All dengue-specific readiness values, occupancy, NS1/RDT stock, IV fluid stock,
    and consumption figures are SYNTHETIC. They do not represent actual facility
    records, current occupancy, or validated operational capacity.

    Zone distribution:
      Z01 Kamrangirchar    : 2 facilities (1 real anchor, 1 synthetic)
      Z02 Mitford/Old Dhaka: 3 facilities (2 real anchors, 1 synthetic)
      Z03 Dhanmondi        : 2 facilities (1 real anchor, 1 synthetic)
      Z04 Jatrabari/Sayedabad: 2 facilities (1 real anchor, 1 synthetic)
      Z05 Lalbagh/Hazaribagh : 2 facilities (2 synthetic local units)
    """
    return [
        # ── Z01: Kamrangirchar ────────────────────────────────────────────────
        {
            "facility_id": "F01",
            "zone_id": "Z01",
            "facility_name": "Kamrangirchar 31-Bed Hospital",
            "facility_type": "Government Upazila Health Complex",
            "facility_anchor_type": "real_public_hospital_anchor",
            "general_bed_capacity": 31,
            "dengue_bed_capacity_demo": 20,
            "occupied_dengue_beds_demo": 16,
            "avg_length_of_stay": 4.5,
            "baseline_daily_dengue_cases_demo": 6,
            "bed_capacity_source": "public_reference_anchor",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Named after its 31-bed capacity. Publicly known government facility in "
                "Kamrangirchar. General bed count is a public reference. All dengue bed "
                "allocation, occupancy, and inventory values are synthetic demo figures."
            ),
        },
        {
            "facility_id": "F02",
            "zone_id": "Z01",
            "facility_name": "Kamrangirchar Urban Health Response Unit",
            "facility_type": "Synthetic Local Health Response Unit",
            "facility_anchor_type": "synthetic_local_response_unit",
            "general_bed_capacity": 10,
            "dengue_bed_capacity_demo": 8,
            "occupied_dengue_beds_demo": 5,
            "avg_length_of_stay": 3.0,
            "baseline_daily_dengue_cases_demo": 3,
            "bed_capacity_source": "synthetic_demo_assumption",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Synthetic local response unit profile for Kamrangirchar zone coverage. "
                "All values are synthetic demo assumptions."
            ),
        },
        # ── Z02: Mitford / Old Dhaka ──────────────────────────────────────────
        {
            "facility_id": "F03",
            "zone_id": "Z02",
            "facility_name": "Sir Salimullah Medical College & Mitford Hospital",
            "facility_type": "Government Medical College Teaching Hospital",
            "facility_anchor_type": "real_public_hospital_anchor",
            "general_bed_capacity": 900,
            "dengue_bed_capacity_demo": 80,
            "occupied_dengue_beds_demo": 63,
            "avg_length_of_stay": 5.0,
            "baseline_daily_dengue_cases_demo": 18,
            "bed_capacity_source": "public_reference_anchor",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Sir Salimullah Medical College & Mitford Hospital is a major government "
                "teaching hospital in Old Dhaka. General bed count (~900) is a publicly "
                "available reference figure. Dengue bed allocation and all readiness/inventory "
                "values are synthetic demonstration figures only."
            ),
        },
        {
            "facility_id": "F04",
            "zone_id": "Z02",
            "facility_name": "Dhaka Medical College Hospital",
            "facility_type": "Government Medical College Teaching Hospital",
            "facility_anchor_type": "real_public_hospital_anchor",
            "general_bed_capacity": 2600,
            "dengue_bed_capacity_demo": 100,
            "occupied_dengue_beds_demo": 78,
            "avg_length_of_stay": 5.2,
            "baseline_daily_dengue_cases_demo": 22,
            "bed_capacity_source": "public_reference_anchor",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Dhaka Medical College Hospital is the largest government teaching hospital "
                "in Bangladesh. General bed count (~2,600) is a publicly available reference. "
                "Dengue bed allocation and all readiness/inventory values are synthetic demo "
                "figures — this prototype does not claim any data about DMCH current operations."
            ),
        },
        {
            "facility_id": "F05",
            "zone_id": "Z02",
            "facility_name": "Old Dhaka Dengue Triage Extension Unit",
            "facility_type": "Synthetic Dengue Triage Extension Unit",
            "facility_anchor_type": "synthetic_local_response_unit",
            "general_bed_capacity": 20,
            "dengue_bed_capacity_demo": 18,
            "occupied_dengue_beds_demo": 12,
            "avg_length_of_stay": 3.5,
            "baseline_daily_dengue_cases_demo": 5,
            "bed_capacity_source": "synthetic_demo_assumption",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Synthetic triage extension unit profile for Old Dhaka / Mitford zone. "
                "All values are synthetic demo assumptions."
            ),
        },
        # ── Z03: Dhanmondi ────────────────────────────────────────────────────
        {
            "facility_id": "F06",
            "zone_id": "Z03",
            "facility_name": "National Institute of Burn and Plastic Surgery",
            "facility_type": "Government Specialized Hospital",
            "facility_anchor_type": "real_public_hospital_anchor",
            "general_bed_capacity": 300,
            "dengue_bed_capacity_demo": 15,
            "occupied_dengue_beds_demo": 9,
            "avg_length_of_stay": 4.0,
            "baseline_daily_dengue_cases_demo": 3,
            "bed_capacity_source": "public_reference_anchor",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "National Institute of Burn and Plastic Surgery is a government specialized "
                "hospital. Included as a nearby surge overflow reference anchor for the Dhanmondi "
                "zone. General bed count (~300) is a public reference. Dengue bed allocation "
                "and all readiness/inventory values are synthetic demo figures."
            ),
        },
        {
            "facility_id": "F07",
            "zone_id": "Z03",
            "facility_name": "Dhanmondi Diagnostic Support Unit",
            "facility_type": "Synthetic Urban Diagnostic Support Unit",
            "facility_anchor_type": "synthetic_local_response_unit",
            "general_bed_capacity": 14,
            "dengue_bed_capacity_demo": 12,
            "occupied_dengue_beds_demo": 7,
            "avg_length_of_stay": 3.5,
            "baseline_daily_dengue_cases_demo": 4,
            "bed_capacity_source": "synthetic_demo_assumption",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Synthetic diagnostic support unit profile for Dhanmondi zone. "
                "All values are synthetic demo assumptions."
            ),
        },
        # ── Z04: Jatrabari / Sayedabad ────────────────────────────────────────
        {
            "facility_id": "F08",
            "zone_id": "Z04",
            "facility_name": "Mugda Medical College Hospital",
            "facility_type": "Government Medical College Hospital",
            "facility_anchor_type": "real_public_hospital_anchor",
            "general_bed_capacity": 500,
            "dengue_bed_capacity_demo": 55,
            "occupied_dengue_beds_demo": 42,
            "avg_length_of_stay": 4.8,
            "baseline_daily_dengue_cases_demo": 13,
            "bed_capacity_source": "public_reference_anchor",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Mugda Medical College Hospital is a government medical college hospital "
                "in Jatrabari. General bed count (~500) is a publicly available reference. "
                "Dengue bed allocation and all readiness/inventory values are synthetic."
            ),
        },
        {
            "facility_id": "F09",
            "zone_id": "Z04",
            "facility_name": "Jatrabari-Sayedabad Public Health Response Unit",
            "facility_type": "Synthetic Public Health Response Unit",
            "facility_anchor_type": "synthetic_local_response_unit",
            "general_bed_capacity": 28,
            "dengue_bed_capacity_demo": 25,
            "occupied_dengue_beds_demo": 19,
            "avg_length_of_stay": 4.5,
            "baseline_daily_dengue_cases_demo": 7,
            "bed_capacity_source": "synthetic_demo_assumption",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Synthetic public health response unit profile for Jatrabari-Sayedabad zone. "
                "All values are synthetic demo assumptions."
            ),
        },
        # ── Z05: Lalbagh / Hazaribagh ─────────────────────────────────────────
        {
            "facility_id": "F10",
            "zone_id": "Z05",
            "facility_name": "Lalbagh Urban Health Response Unit",
            "facility_type": "Synthetic Urban Health Response Unit",
            "facility_anchor_type": "synthetic_local_response_unit",
            "general_bed_capacity": 20,
            "dengue_bed_capacity_demo": 18,
            "occupied_dengue_beds_demo": 13,
            "avg_length_of_stay": 4.2,
            "baseline_daily_dengue_cases_demo": 5,
            "bed_capacity_source": "synthetic_demo_assumption",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Synthetic urban health response unit profile for Lalbagh zone. "
                "All values are synthetic demo assumptions."
            ),
        },
        {
            "facility_id": "F11",
            "zone_id": "Z05",
            "facility_name": "Hazaribagh Urban Health Response Unit",
            "facility_type": "Synthetic Urban Health Response Unit",
            "facility_anchor_type": "synthetic_local_response_unit",
            "general_bed_capacity": 18,
            "dengue_bed_capacity_demo": 16,
            "occupied_dengue_beds_demo": 11,
            "avg_length_of_stay": 4.0,
            "baseline_daily_dengue_cases_demo": 5,
            "bed_capacity_source": "synthetic_demo_assumption",
            "readiness_data_status": "synthetic_operational_readiness",
            "inventory_data_status": "synthetic_inventory_demo",
            "notes": (
                "Synthetic urban health response unit profile for Hazaribagh zone. "
                "All values are synthetic demo assumptions."
            ),
        },
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 5. INVENTORY
# ─────────────────────────────────────────────────────────────────────────────

def generate_inventory() -> list[dict]:
    """
    Generate NS1/RDT kit and IV fluid inventory for all 11 facilities (22 items total).

    Capacity tiers:
      Large public hospitals (DMCH F04, SSMC F03, Mugda F08):
          Higher absolute stock; higher baseline consumption.
      Mid-size hospitals and response units (F01, F08, F09):
          Moderate stock; moderate consumption.
      Small health posts and synthetic units (F02, F05, F06, F07, F10, F11):
          Lower stock; lower consumption.

    Design signal:
      All facilities are intentionally in the 10–18 day baseline SDH range —
      adequate under non-surge conditions but stressed under expected/worst-case
      scenarios. This creates the intended preparedness signal on the dashboard.

    All values are SYNTHETIC. Not representative of actual facility inventory records.
    """
    return [
        # ── F01: Kamrangirchar 31-Bed Hospital ────────────────────────────────
        {"inventory_id": "INV-F01-NS1", "facility_id": "F01",
         "item_name": "NS1/RDT Kit",     "current_stock": 78,
         "baseline_daily_consumption": 7, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F01-IVF", "facility_id": "F01",
         "item_name": "IV Fluid (500ml)", "current_stock": 195,
         "baseline_daily_consumption": 16, "reorder_threshold_days": 5},

        # ── F02: Kamrangirchar Urban Health Post (Synthetic) ──────────────────
        {"inventory_id": "INV-F02-NS1", "facility_id": "F02",
         "item_name": "NS1/RDT Kit",     "current_stock": 42,
         "baseline_daily_consumption": 4, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F02-IVF", "facility_id": "F02",
         "item_name": "IV Fluid (500ml)", "current_stock": 105,
         "baseline_daily_consumption": 9, "reorder_threshold_days": 5},

        # ── F03: Sir Salimullah Medical College & Mitford Hospital ────────────
        {"inventory_id": "INV-F03-NS1", "facility_id": "F03",
         "item_name": "NS1/RDT Kit",     "current_stock": 310,
         "baseline_daily_consumption": 22, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F03-IVF", "facility_id": "F03",
         "item_name": "IV Fluid (500ml)", "current_stock": 720,
         "baseline_daily_consumption": 56, "reorder_threshold_days": 5},

        # ── F04: Dhaka Medical College Hospital ───────────────────────────────
        {"inventory_id": "INV-F04-NS1", "facility_id": "F04",
         "item_name": "NS1/RDT Kit",     "current_stock": 400,
         "baseline_daily_consumption": 28, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F04-IVF", "facility_id": "F04",
         "item_name": "IV Fluid (500ml)", "current_stock": 900,
         "baseline_daily_consumption": 70, "reorder_threshold_days": 5},

        # ── F05: Old Dhaka Dengue Triage Extension Unit (Synthetic) ──────────
        {"inventory_id": "INV-F05-NS1", "facility_id": "F05",
         "item_name": "NS1/RDT Kit",     "current_stock": 65,
         "baseline_daily_consumption": 6, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F05-IVF", "facility_id": "F05",
         "item_name": "IV Fluid (500ml)", "current_stock": 160,
         "baseline_daily_consumption": 13, "reorder_threshold_days": 5},

        # ── F06: National Institute of Burn and Plastic Surgery ───────────────
        {"inventory_id": "INV-F06-NS1", "facility_id": "F06",
         "item_name": "NS1/RDT Kit",     "current_stock": 38,
         "baseline_daily_consumption": 4, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F06-IVF", "facility_id": "F06",
         "item_name": "IV Fluid (500ml)", "current_stock": 90,
         "baseline_daily_consumption": 8, "reorder_threshold_days": 5},

        # ── F07: Dhanmondi Public Diagnostic Support Unit (Synthetic) ─────────
        {"inventory_id": "INV-F07-NS1", "facility_id": "F07",
         "item_name": "NS1/RDT Kit",     "current_stock": 62,
         "baseline_daily_consumption": 5, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F07-IVF", "facility_id": "F07",
         "item_name": "IV Fluid (500ml)", "current_stock": 145,
         "baseline_daily_consumption": 11, "reorder_threshold_days": 5},

        # ── F08: Mugda Medical College Hospital ───────────────────────────────
        {"inventory_id": "INV-F08-NS1", "facility_id": "F08",
         "item_name": "NS1/RDT Kit",     "current_stock": 250,
         "baseline_daily_consumption": 18, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F08-IVF", "facility_id": "F08",
         "item_name": "IV Fluid (500ml)", "current_stock": 560,
         "baseline_daily_consumption": 44, "reorder_threshold_days": 5},

        # ── F09: Jatrabari-Sayedabad Public Health Response Unit (Synthetic) ──
        {"inventory_id": "INV-F09-NS1", "facility_id": "F09",
         "item_name": "NS1/RDT Kit",     "current_stock": 140,
         "baseline_daily_consumption": 10, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F09-IVF", "facility_id": "F09",
         "item_name": "IV Fluid (500ml)", "current_stock": 340,
         "baseline_daily_consumption": 28, "reorder_threshold_days": 5},

        # ── F10: Lalbagh Urban Health Facility (Synthetic) ────────────────────
        {"inventory_id": "INV-F10-NS1", "facility_id": "F10",
         "item_name": "NS1/RDT Kit",     "current_stock": 92,
         "baseline_daily_consumption": 8, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F10-IVF", "facility_id": "F10",
         "item_name": "IV Fluid (500ml)", "current_stock": 210,
         "baseline_daily_consumption": 17, "reorder_threshold_days": 5},

        # ── F11: Hazaribagh Urban Health Facility (Synthetic) ─────────────────
        {"inventory_id": "INV-F11-NS1", "facility_id": "F11",
         "item_name": "NS1/RDT Kit",     "current_stock": 82,
         "baseline_daily_consumption": 7, "reorder_threshold_days": 7},
        {"inventory_id": "INV-F11-IVF", "facility_id": "F11",
         "item_name": "IV Fluid (500ml)", "current_stock": 190,
         "baseline_daily_consumption": 16, "reorder_threshold_days": 5},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# 6. WRITE FILES
# ─────────────────────────────────────────────────────────────────────────────

def write_csv(df: pd.DataFrame, path: Path, label: str) -> None:
    df.to_csv(path, index=False)
    print(f"  [OK] {label}")
    print(f"       Path  : {path}")
    print(f"       Shape : {df.shape[0]} rows x {df.shape[1]} columns")
    print(f"       Cols  : {', '.join(df.columns.tolist())}")


def write_json(data: list | dict, path: Path, label: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    n = len(data) if isinstance(data, list) else 1
    print(f"  [OK] {label}")
    print(f"       Path  : {path}")
    print(f"       Items : {n}")


def print_summary(df_cases: pd.DataFrame, df_climate: pd.DataFrame) -> None:
    """Print descriptive summary of generated data."""
    sep = "-" * 60
    print("\n" + sep)
    print("  DATA SUMMARY")
    print(sep)

    print("\n  Dengue Cases:")
    for year in [2024, 2025, 2026]:
        sub = df_cases[df_cases["epi_year"] == year]
        if sub.empty:
            continue
        peak_row = sub.loc[sub["cases"].idxmax()]
        print(f"    {year}  weeks={len(sub):3d}  "
              f"total_cases={int(sub['cases'].sum()):7,d}  "
              f"peak_cases={int(sub['cases'].max()):6,d} (week {int(peak_row['epi_week'])})"
              f"  deaths={int(sub['deaths'].sum()):3d}")

    print("\n  Climate:")
    for year in [2024, 2025, 2026]:
        sub = df_climate[df_climate["epi_year"] == year]
        if sub.empty: continue
        print(f"    {year}  rain_peak={sub['rainfall_mm'].max():5.1f}mm  "
              f"temp_range=[{sub['avg_temp_c'].min():.1f},{sub['avg_temp_c'].max():.1f}]C  "
              f"hum_range=[{sub['humidity_pct'].min():.1f},{sub['humidity_pct'].max():.1f}]%")

    facilities_all = generate_facilities()
    real_count = sum(1 for f in facilities_all if f.get("facility_anchor_type") == "real_public_hospital_anchor")
    syn_count = len(facilities_all) - real_count
    print("\n  Zones (exposure_index):")
    for z in generate_zones():
        print(f"    {z['zone_id']} {z['zone_name']:<28}  "
              f"exposure={z['exposure_index']:.4f}  vuln={z['vulnerability_weight']:.2f}")

    print(f"\n  Facilities: {len(facilities_all)} total  "
          f"({real_count} real public hospital anchors, {syn_count} synthetic local response units)")
    zone_fac_count: dict[str, int] = {}
    for f in facilities_all:
        zone_fac_count[f["zone_id"]] = zone_fac_count.get(f["zone_id"], 0) + 1
    for zid, cnt in sorted(zone_fac_count.items()):
        print(f"    {zid}: {cnt} facilit{'y' if cnt == 1 else 'ies'}")

    print("\n  Inventory (baseline SDH = stock / daily_consumption):")
    for inv in generate_inventory():
        sdh = inv["current_stock"] / inv["baseline_daily_consumption"]
        print(f"    {inv['inventory_id']:<18}  "
              f"stock={inv['current_stock']:4d}  "
              f"daily={inv['baseline_daily_consumption']:3d}  "
              f"SDH={sdh:.1f}d  "
              f"threshold={inv['reorder_threshold_days']}d")
    print(sep + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

ALL_DOMAINS = ("cases", "climate", "operational")


def main(
    domains: set[str] | None = None,
    output_dir: Path = DATA_DIR,
) -> None:
    global rng

    selected_domains = set(ALL_DOMAINS if domains is None else domains)
    unknown_domains = selected_domains - set(ALL_DOMAINS)
    if unknown_domains:
        raise ValueError(f"Unknown demo output domains: {sorted(unknown_domains)}")

    # Re-seed each invocation so selective and repeated in-process runs remain
    # identical to the original standalone generation order.
    rng = np.random.default_rng(RANDOM_SEED)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 60)
    print("  DengueOps AI — Phase 1: Demo Data Generation")
    print("  Mode: Controlled Dhaka South synthetic/demo dataset (2024-2026)")
    print("  Domains:", ", ".join(domain for domain in ALL_DOMAINS if domain in selected_domains))
    print("  Random seed:", RANDOM_SEED)
    print("  Output dir :", output_dir)
    print("=" * 60 + "\n")

    print("  Generating files...\n")

    # Always calculate cases then climate in the original order so selective
    # writes do not change the deterministic synthetic values.
    df_cases = generate_dengue_cases()
    df_climate = generate_climate_data()

    if "cases" in selected_domains:
        write_csv(df_cases, output_dir / "dengue_cases.csv", "dengue_cases.csv")

    if "climate" in selected_domains:
        write_csv(df_climate, output_dir / "climate_data.csv", "climate_data.csv")

    if "operational" in selected_domains:
        write_json(generate_zones(), output_dir / "zones.json", "zones.json")
        write_json(generate_facilities(), output_dir / "facilities.json", "facilities.json")
        write_json(generate_inventory(), output_dir / "inventory.json", "inventory.json")

    if selected_domains == set(ALL_DOMAINS):
        print_summary(df_cases, df_climate)

    print("=" * 60)
    print("  Selected demo data files generated successfully.")
    print("  IMPORTANT: All values are SYNTHETIC DEMO DATA only.")
    print("  Real public hospital names used as credible location anchors.")
    print("  General bed capacities are public reference figures only.")
    print("  Dengue bed allocation, occupancy, NS1/RDT stock, IV fluid stock,")
    print("  and consumption rates are SYNTHETIC demonstration values.")
    print("  No patient-level or personal health data was generated.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate selected DengueOps synthetic demo input domains.",
    )
    parser.add_argument(
        "--domains",
        nargs="+",
        choices=ALL_DOMAINS,
        default=list(ALL_DOMAINS),
        help="Input domains to write (default: cases climate operational).",
    )
    args = parser.parse_args()
    main(domains=set(args.domains))
