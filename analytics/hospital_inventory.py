"""Strict schema and semantic validation for governed hospital inventory."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from deployment_scope import load_product_scope

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "config" / "hospital_inventory.schema.json"
SEED_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "hospital_inventory.json"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")


class HospitalInventoryError(ValueError):
    """Raised when governed hospital inventory is invalid."""


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def raw_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _normalized_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate_inventory(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HospitalInventoryError("Hospital inventory must be a JSON object.")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise HospitalInventoryError(f"Hospital inventory failed schema validation: {errors[0].message}")
    scope = load_product_scope(value["deploymentId"])
    if value["deploymentDisplayName"] != scope["deploymentDisplayName"]:
        raise HospitalInventoryError("Inventory display scope differs from product-scope authority.")
    references = value["sourceReferences"]
    reference_ids = [reference["verificationReferenceId"] for reference in references]
    if len(reference_ids) != len(set(reference_ids)):
        raise HospitalInventoryError("Duplicate verification reference ID.")
    known_references = set(reference_ids)
    hospital_ids = [hospital["hospitalId"] for hospital in value["hospitals"]]
    if len(hospital_ids) != len(set(hospital_ids)):
        raise HospitalInventoryError("Duplicate hospital ID.")
    active_names = [_normalized_name(hospital["officialName"]) for hospital in value["hospitals"] if hospital["active"]]
    if len(active_names) != len(set(active_names)):
        raise HospitalInventoryError("Duplicate normalized official name among active hospitals.")
    current_participation_contract = int(value["inventoryVersion"].split(".", 1)[0]) >= 3
    for hospital in value["hospitals"]:
        if current_participation_contract and not {
            "participationStatus", "managementDecisionStatus",
            "selectedBedCapacity", "currentAvailableBeds",
        }.issubset(hospital):
            raise HospitalInventoryError("Current inventory is missing participation authority fields.")
        if hospital.get("participationStatus") == "included":
            if not hospital["active"] or hospital["managementDecisionStatus"] != "pending_review":
                raise HospitalInventoryError("Included participation requires an active pending-review hospital.")
        elif "managementDecisionStatus" in hospital and hospital["managementDecisionStatus"] != "not_applicable":
            raise HospitalInventoryError("Non-participating hospitals cannot carry a management decision.")
        if hospital.get("currentAvailableBeds") is not None:
            raise HospitalInventoryError("Current available beds must remain unknown.")
        identity_reference = hospital["identityVerification"]["verificationReferenceId"]
        if identity_reference not in known_references:
            raise HospitalInventoryError(f"Hospital {hospital['hospitalId']} uses an unknown identity reference.")
        resource_types: set[str] = set()
        for resource in hospital["resources"]:
            if resource["verificationReferenceId"] not in known_references:
                raise HospitalInventoryError(f"Hospital {hospital['hospitalId']} resource uses an unknown reference.")
            if resource["resourceType"] in resource_types:
                raise HospitalInventoryError(f"Hospital {hospital['hospitalId']} has a duplicate resource type.")
            resource_types.add(resource["resourceType"])
            if resource["quantity"] is None and resource["dataStatus"] not in {"unknown", "unavailable"}:
                raise HospitalInventoryError("Null resource quantity must be explicitly unknown or unavailable.")
            if resource["quantity"] is not None and resource["dataStatus"] not in {"verified", "reported", "verified_capacity_reference"}:
                raise HospitalInventoryError("Known resource quantity requires verified or reported status.")
            if resource["resourceType"] == "available_beds" and resource["quantity"] is not None:
                raise HospitalInventoryError("Official seed cannot assert current available beds.")
            if resource["resourceType"] == "total_bed_capacity":
                if resource["quantity"] is not None and resource["dataStatus"] != "verified_capacity_reference":
                    raise HospitalInventoryError("Official capacity must be labelled as a capacity reference.")
                if resource["availabilityStatus"] != "not_known":
                    raise HospitalInventoryError("Official capacity cannot assert current availability.")
    active = [hospital for hospital in value["hospitals"] if hospital["active"]]
    if value["allocationStatus"] == "not_configured":
        if any(hospital["allocationShare"] != {"status": "not_configured", "value": None} for hospital in value["hospitals"]):
            raise HospitalInventoryError("Unconfigured allocation cannot contain shares.")
    else:
        if any(hospital["allocationShare"]["status"] != "configured" for hospital in active):
            raise HospitalInventoryError("Every active hospital requires a configured allocation share.")
        try:
            total = sum((Decimal(hospital["allocationShare"]["value"]) for hospital in active), Decimal(0))
        except (InvalidOperation, TypeError) as exc:
            raise HospitalInventoryError("Allocation share is not a valid fixed-scale decimal.") from exc
        if total != Decimal("1.000000"):
            raise HospitalInventoryError("Active hospital allocation shares must sum exactly to 1.000000.")
    return dict(value)


def load_inventory(path: str | Path = SEED_PATH) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HospitalInventoryError("Hospital inventory is unreadable.") from exc
    return validate_inventory(value)


def inventory_diff(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    before = {hospital["hospitalId"]: hospital for hospital in left["hospitals"]}
    after = {hospital["hospitalId"]: hospital for hospital in right["hospitals"]}
    return {
        "fromInventoryId": left["inventoryId"],
        "toInventoryId": right["inventoryId"],
        "addedHospitalIds": sorted(after.keys() - before.keys()),
        "removedHospitalIds": sorted(before.keys() - after.keys()),
        "changedHospitalIds": sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
        "deactivatedHospitalIds": sorted(
            key for key in before.keys() & after.keys() if before[key]["active"] and not after[key]["active"]
        ),
    }


def source_reference_snapshot(inventory: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "inventoryId": inventory["inventoryId"],
        "sourceReferences": inventory["sourceReferences"],
    }
