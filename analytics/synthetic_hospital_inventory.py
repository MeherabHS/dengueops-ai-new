"""Deterministic qualification-only inventory generation and validation."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from hospital_capacity_reference import load_capacity_reference

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "qualification" / "synthetic_inventory_scenario_policy.json"
POLICY_SCHEMA = ROOT / "config" / "synthetic_inventory_scenario_policy.schema.json"
INVENTORY_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "qualification" / "synthetic_hospital_inventory.json"
INVENTORY_SCHEMA = ROOT / "config" / "synthetic_hospital_inventory.schema.json"
LIMITATIONS = [
    "Not estimated current occupancy.",
    "Not hospital-reported availability.",
    "Not a dengue bed allocation.",
    "Not validated against live hospital operations; used only to exercise preparedness software behavior.",
]


class SyntheticHospitalInventoryError(ValueError):
    """Raised when synthetic qualification authority is invalid."""


def canonical_sha256(value: dict[str, Any], excluded: frozenset[str] = frozenset()) -> str:
    content = {key: child for key, child in value.items() if key not in excluded}
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _schema(value: Any, path: Path) -> None:
    schema = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise SyntheticHospitalInventoryError(f"Synthetic authority schema failure: {errors[0].message}")


def validate_scenario_policy(value: Any) -> dict[str, Any]:
    _schema(value, POLICY_SCHEMA)
    if value["policySha256"] != canonical_sha256(value, frozenset({"policySha256"})):
        raise SyntheticHospitalInventoryError("Synthetic scenario policy hash mismatch.")
    return dict(value)


def load_scenario_policy(path: str | Path = POLICY_PATH) -> dict[str, Any]:
    return validate_scenario_policy(json.loads(Path(path).read_text(encoding="utf-8")))


def _shares(
    hospitals: list[dict[str, Any]],
    *,
    require_legacy_eligibility: bool = False,
) -> dict[str, str]:
    eligible = [
        hospital for hospital in hospitals
        if hospital["selectedBedCapacity"]["quantity"] is not None
        and (
            not require_legacy_eligibility
            or hospital["denguePreparednessEligibility"] in {"eligible", "potentially_eligible"}
        )
    ]
    total = sum(hospital["selectedBedCapacity"]["quantity"] for hospital in eligible)
    if total <= 0:
        raise SyntheticHospitalInventoryError("Qualification allocation has no eligible capacity.")
    scale = 1_000_000
    exact = {
        hospital["hospitalId"]: Decimal(hospital["selectedBedCapacity"]["quantity"]) * scale / Decimal(total)
        for hospital in eligible
    }
    units = {key: int(value.to_integral_value(rounding=ROUND_FLOOR)) for key, value in exact.items()}
    remainder = scale - sum(units.values())
    order = sorted(exact, key=lambda key: (-(exact[key] - units[key]), key))
    for key in order[:remainder]:
        units[key] += 1
    return {key: f"{value / scale:.6f}" for key, value in units.items()}


def generate_synthetic_inventory(
    reference: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    official = reference or load_capacity_reference()
    scenario_policy = policy or load_scenario_policy()
    hospital_by_id = {hospital["hospitalId"]: hospital for hospital in official["hospitals"]}
    current_participation_contract = scenario_policy["policyVersion"] == "b8.5-v2"
    if current_participation_contract:
        participating_ids = scenario_policy["participatingHospitalIds"]
        missing_ids = [hospital_id for hospital_id in participating_ids if hospital_id not in hospital_by_id]
        if missing_ids:
            raise SyntheticHospitalInventoryError(
                f"Participation policy references unknown hospitals: {', '.join(missing_ids)}"
            )
        participating = [hospital_by_id[hospital_id] for hospital_id in participating_ids]
    else:
        participating = official["hospitals"]
    shares = _shares(participating, require_legacy_eligibility=not current_participation_contract)
    scenarios = []
    for scenario_id, fraction_text in scenario_policy["availabilityScenarios"].items():
        fraction = Decimal(fraction_text)
        rows = []
        for hospital in participating:
            capacity = hospital["selectedBedCapacity"]["quantity"]
            eligibility = hospital["denguePreparednessEligibility"]
            if not current_participation_contract and eligibility not in {"eligible", "potentially_eligible"}:
                status = "not_eligible" if eligibility == "not_eligible" else "eligibility_not_verified"
                allocation, quantity, result = None, None, status
            elif capacity is None:
                allocation, quantity, status, result = None, None, "insufficient_capacity_reference", "insufficient_capacity_reference"
            else:
                allocation = shares[hospital["hospitalId"]]
                quantity = int((Decimal(capacity) * fraction).to_integral_value(rounding=ROUND_FLOOR))
                status, result = "configured", "synthetic_value_generated"
            row = {
                "hospitalId": hospital["hospitalId"],
                "eligibility": eligibility,
                "allocationShare": allocation,
                "allocationStatus": status,
                "synthetic": True,
                "generationMethod": "floor_selected_bed_capacity_times_governed_fraction",
                "scenarioParameterIdentity": f"{scenario_policy['policyId']}:{scenario_policy['policyVersion']}:{scenario_id}",
                "officialCapacityReference": {
                    "quantity": capacity,
                    "unit": "beds",
                    "capacityReferenceSha256": official["capacityReferenceCanonicalSha256"],
                },
                "quantity": quantity,
                "unit": "bed_units",
                "resultStatus": result,
                "limitations": LIMITATIONS,
            }
            if current_participation_contract:
                row["participationStatus"] = "included"
                row["managementDecisionStatus"] = scenario_policy["participationDecisionStatus"]
            rows.append(row)
        scenarios.append({
            "scenarioId": scenario_id,
            "availabilityFraction": fraction_text,
            "allocationShareTotal": "1.000000",
            "hospitals": rows,
        })
    value = {
        "schemaVersion": "1.0",
        "syntheticInventoryId": (
            "dhaka-hospital-qualification-20260729-v2"
            if current_participation_contract
            else "dhaka-hospital-qualification-20260728-v1"
        ),
        "syntheticInventoryVersion": "2.0.0" if current_participation_contract else "1.0.0",
        "derivedFromOfficialCapacityReferenceId": official["capacityReferenceId"],
        "derivedFromOfficialCapacityReferenceSha256": official["capacityReferenceCanonicalSha256"],
        "evidenceScope": "synthetic_qualification",
        "operationalDhakaValidation": False,
        "syntheticData": True,
        "operationalUseAllowed": False,
        "clinicalUseAllowed": False,
        "hospitalDecisionUseAllowed": False,
        "scenarioPolicyId": scenario_policy["policyId"],
        "scenarioPolicySha256": scenario_policy["policySha256"],
        "allocationMethod": scenario_policy["allocationMethod"],
        "operationalAllocationApproved": False,
        "scenarios": scenarios,
        "syntheticInventorySha256": "",
    }
    value["syntheticInventorySha256"] = canonical_sha256(value, frozenset({"syntheticInventorySha256"}))
    return value


def validate_synthetic_inventory(
    value: Any,
    *,
    reference: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _schema(value, INVENTORY_SCHEMA)
    if value["syntheticInventorySha256"] != canonical_sha256(value, frozenset({"syntheticInventorySha256"})):
        raise SyntheticHospitalInventoryError("Synthetic inventory hash mismatch.")
    generated = generate_synthetic_inventory(reference, policy)
    if value != generated:
        raise SyntheticHospitalInventoryError("Synthetic inventory differs from deterministic governed derivation.")
    for scenario in value["scenarios"]:
        configured = [Decimal(row["allocationShare"]) for row in scenario["hospitals"] if row["allocationStatus"] == "configured"]
        if sum(configured, Decimal(0)) != Decimal("1.000000"):
            raise SyntheticHospitalInventoryError("Qualification allocation does not sum exactly to 1.000000.")
    return dict(value)


def load_synthetic_inventory(path: str | Path = INVENTORY_PATH) -> dict[str, Any]:
    return validate_synthetic_inventory(json.loads(Path(path).read_text(encoding="utf-8")))


def write_synthetic_inventory(path: str | Path = INVENTORY_PATH) -> dict[str, Any]:
    target = Path(path)
    value = generate_synthetic_inventory()
    validate_synthetic_inventory(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return value
