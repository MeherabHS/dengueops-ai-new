"""Build synthetic system-qualification preparedness evidence downstream of forecast authority."""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from typing import Any

from formula_inputs import allowed_variable_names
from formula_policy import resolve_qualification_formula
from safe_formula import evaluate_formula_canonical
from synthetic_hospital_inventory import LIMITATIONS, load_scenario_policy, load_synthetic_inventory


class HospitalPreparednessError(ValueError):
    """Raised when qualification evidence cannot be calculated safely."""


def _allocate_cases(total: int, rows: list[dict[str, Any]]) -> dict[str, int]:
    eligible = [row for row in rows if row["allocationStatus"] == "configured"]
    exact = {row["hospitalId"]: Decimal(total) * Decimal(row["allocationShare"]) for row in eligible}
    allocated = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in exact.items()}
    remainder = total - sum(allocated.values())
    order = sorted(exact, key=lambda key: (-(exact[key] - allocated[key]), key))
    for key in order[:remainder]:
        allocated[key] += 1
    return allocated


def build_preparedness_evidence(
    source: dict[str, Any],
    scenario_id: str,
    preparedness_id: str,
    generated_at: str,
) -> dict[str, Any]:
    inventory = load_synthetic_inventory()
    scenario_policy = load_scenario_policy()
    formula = resolve_qualification_formula("inventory.gap", requested_evidence_scope="synthetic_qualification")
    scenario = next((item for item in inventory["scenarios"] if item["scenarioId"] == scenario_id), None)
    if scenario is None:
        raise HospitalPreparednessError("synthetic_inventory_unavailable")
    forecast = source["bundle"]["forecast"]
    forecast_cases = forecast.get("forecastReported")
    if not isinstance(forecast_cases, int) or forecast_cases < 0:
        raise HospitalPreparednessError("source_verification_failed")
    allocations = _allocate_cases(forecast_cases, scenario["hospitals"])
    hospitals = []
    for row in scenario["hospitals"]:
        if row["allocationStatus"] != "configured":
            status = row["resultStatus"]
            hospitals.append({
                "hospitalId": row["hospitalId"], "status": status,
                "allocationShare": row["allocationShare"], "allocatedForecastCases": None,
                "availableResource": row["quantity"], "resourcePerCase": None,
                "formulaId": None, "formulaSha256": None, "syntheticGap": None,
                "unit": "bed_units", "limitations": LIMITATIONS,
            })
            continue
        inputs = {
            "allocatedForecastCases": allocations[row["hospitalId"]],
            "resourcePerCase": scenario_policy["coefficient"]["resourcePerCase"],
            "availableResource": row["quantity"],
        }
        gap = evaluate_formula_canonical(
            formula["expression"], inputs, allowed_variables=allowed_variable_names("inventory.gap")
        )
        hospitals.append({
            "hospitalId": row["hospitalId"],
            "status": "calculated_synthetic_gap_present" if Decimal(gap) > 0 else "no_calculated_synthetic_gap",
            "allocationShare": row["allocationShare"],
            "allocatedForecastCases": allocations[row["hospitalId"]],
            "availableResource": row["quantity"],
            "resourcePerCase": scenario_policy["coefficient"]["resourcePerCase"],
            "formulaId": formula["formulaId"],
            "formulaSha256": formula["formulaSha256"],
            "syntheticGap": gap,
            "unit": "bed_units",
            "limitations": LIMITATIONS,
        })
    bundle = source["bundle"]
    return {
        "schemaVersion": "1.0",
        "preparednessId": preparedness_id,
        "scenarioId": scenario_id,
        "deploymentId": "dhaka_south",
        "deploymentDisplayName": "Dhaka",
        "evidenceScope": "synthetic_qualification",
        "operationalDhakaValidation": False,
        "officialHospitalIdentities": True,
        "officialBedCapacityReferences": "mixed",
        "currentHospitalAvailability": "synthetic",
        "allocationBasis": "synthetic_capacity_proportional_qualification",
        "resourceCoefficientBasis": "synthetic_pipeline_exercise",
        "operationalUseAllowed": False,
        "clinicalUseAllowed": False,
        "hospitalDecisionUseAllowed": False,
        "preparednessInterpretation": "system_behavior_qualification_only",
        "forecastSource": {
            "runId": source["runId"],
            "forecastCommitSha256": source["commitSha256"],
            "sourceFamily": bundle["sourceFamily"],
            "modelId": bundle["modelId"],
            "modelFamily": bundle["modelFamily"],
            "parameterSha256": bundle["parameterHash"],
            "target": forecast["target"],
            "targetPeriod": forecast["targetPeriod"],
            "horizonWeeks": forecast["horizonWeeks"],
            "forecastPresentationMode": forecast.get("forecastPresentationMode", bundle["uncertainty"].get("forecastPresentationMode")),
            "calibrationStatus": forecast.get("calibrationStatus", bundle["uncertainty"].get("calibrationStatus")),
            "forecastReported": forecast_cases,
            "sourcePolicy": bundle["sourcePolicy"],
            "assignment": bundle.get("assignment"),
        },
        "authorityBindings": {
            "syntheticInventoryId": inventory["syntheticInventoryId"],
            "syntheticInventorySha256": inventory["syntheticInventorySha256"],
            "scenarioPolicyId": scenario_policy["policyId"],
            "scenarioPolicySha256": scenario_policy["policySha256"],
            "formulaId": formula["formulaId"],
            "formulaSha256": formula["formulaSha256"],
        },
        "hospitals": hospitals,
        "generatedAt": generated_at,
    }
