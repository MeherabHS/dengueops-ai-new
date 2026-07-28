"""Validation and deterministic identity for official bed-capacity references."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
REFERENCE_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "dhaka_government_hospital_capacity_reference.json"
SCHEMA_PATH = ROOT / "config" / "hospital_capacity_reference.schema.json"
HASH_FIELDS = frozenset({"capacityReferenceCanonicalSha256", "capacityReferenceContentSha256"})


class HospitalCapacityReferenceError(ValueError):
    """Raised when official capacity-reference authority fails closed."""


def _content(value: dict[str, Any]) -> dict[str, Any]:
    return {key: child for key, child in value.items() if key not in HASH_FIELDS}


def canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(_content(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def content_sha256(value: dict[str, Any]) -> str:
    payload = (json.dumps(_content(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def raw_sha256(path: str | Path = REFERENCE_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_capacity_reference(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HospitalCapacityReferenceError("Capacity reference must be an object.")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise HospitalCapacityReferenceError(f"Capacity reference schema failure: {errors[0].message}")
    if value["capacityReferenceCanonicalSha256"] != canonical_sha256(value):
        raise HospitalCapacityReferenceError("Capacity-reference canonical hash mismatch.")
    if value["capacityReferenceContentSha256"] != content_sha256(value):
        raise HospitalCapacityReferenceError("Capacity-reference content hash mismatch.")
    references = {item["verificationReferenceId"] for item in value["sourceReferences"]}
    ids: set[str] = set()
    registry_ids: set[int] = set()
    for hospital in value["hospitals"]:
        if hospital["hospitalId"] in ids or hospital["officialFacilityRegistryId"] in registry_ids:
            raise HospitalCapacityReferenceError("Duplicate hospital or official registry identity.")
        ids.add(hospital["hospitalId"])
        registry_ids.add(hospital["officialFacilityRegistryId"])
        if hospital["verificationReferenceId"] not in references:
            raise HospitalCapacityReferenceError("Hospital capacity uses an unknown source reference.")
        selected = hospital["selectedBedCapacity"]
        if selected["verificationReferenceId"] not in references:
            raise HospitalCapacityReferenceError("Selected capacity uses an unknown source reference.")
        if hospital["latestBedCount"] == 0 and (hospital["approvedBedCount"] or 0) > 0:
            if hospital["latestBedCountStatus"] != "registry_zero_not_accepted_as_operational_zero":
                raise HospitalCapacityReferenceError("Registry zero was accepted as operational capacity.")
            if selected["basis"] == "latest_official_operational_count":
                raise HospitalCapacityReferenceError("Registry zero cannot be selected as operational capacity.")
        if selected["quantity"] is None:
            if selected["basis"] != "unavailable" or selected["dataQualityStatus"] != "unavailable":
                raise HospitalCapacityReferenceError("Unknown selected capacity must remain unavailable.")
        elif selected["quantity"] == 0:
            raise HospitalCapacityReferenceError("Unverified zero cannot become selected capacity.")
        if selected["availabilityStatus"] != "not_known":
            raise HospitalCapacityReferenceError("Capacity reference cannot assert current availability.")
    return dict(value)


def load_capacity_reference(path: str | Path = REFERENCE_PATH) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HospitalCapacityReferenceError("Capacity reference is unreadable.") from exc
    return validate_capacity_reference(value)


def build_official_inventory_seed(reference: dict[str, Any] | None = None) -> dict[str, Any]:
    authority = reference or load_capacity_reference()
    references = [
        {
            "verificationReferenceId": item["verificationReferenceId"],
            "sourceOrganization": item["sourceOrganization"],
            "sourceUrl": item["sourceUrl"],
            "retrievedAt": item["retrievedAt"],
            "verifiedAt": item["retrievedAt"],
            "supportedFields": ["officialName", "ownership", "location", "facilityType", "facilityIdentity", "bedCapacityReference"],
        }
        for item in authority["sourceReferences"]
    ]
    hospitals = []
    for item in authority["hospitals"]:
        source_as_of = item["selectedBedCapacity"]["sourceAsOf"]
        city = item["cityCorporation"]
        location_status = (
            "official_metropolitan_location_city_field_missing"
            if city == "metropolitan_location_registry_field_missing"
            else "official_city_corporation_only"
        )
        quantity = item["selectedBedCapacity"]["quantity"]
        hospitals.append({
            "hospitalId": item["hospitalId"],
            "officialFacilityRegistryId": item["officialFacilityRegistryId"],
            "officialFacilityCode": item["officialFacilityCode"],
            "officialName": item["officialName"],
            "alternateNames": item["alternateNames"],
            "facilityType": item["facilityType"],
            "ownership": "government_autonomous" if item["ownership"] == "government_autonomous" else "public_government",
            "active": True,
            "denguePreparednessEligibility": item["denguePreparednessEligibility"],
            "location": {
                "address": None,
                "administrativeArea": "Dhaka",
                "cityCorporation": city,
                "locationStatus": location_status,
            },
            "identityVerification": {
                "status": "verified",
                "verificationReferenceId": item["verificationReferenceId"],
                "verifiedAt": authority["retrievedAt"],
            },
            "allocationShare": {"status": "not_configured", "value": None},
            "resources": [
                {
                    "resourceType": "total_bed_capacity",
                    "unit": "count",
                    "quantity": quantity,
                    "dataStatus": "verified_capacity_reference" if quantity is not None else "unavailable",
                    "availabilityStatus": "not_known",
                    "asOf": source_as_of if quantity is not None else None,
                    "verificationReferenceId": item["verificationReferenceId"],
                },
                {
                    "resourceType": "available_beds",
                    "unit": "count",
                    "quantity": None,
                    "dataStatus": "unknown",
                    "availabilityStatus": "not_known",
                    "asOf": None,
                    "verificationReferenceId": item["verificationReferenceId"],
                },
            ],
            "limitations": [
                "Official capacity is not current availability.",
                "Current available beds and dengue-bed allocation are unknown.",
            ],
        })
    return {
        "schemaVersion": "1.0",
        "inventoryId": "dhaka-government-hospitals-20260728-v2",
        "inventoryVersion": "2.0.0",
        "deploymentId": "dhaka_south",
        "deploymentDisplayName": "Dhaka",
        "changeReason": "Expand the official inventory to all verified inpatient candidates in the governed 2026-07-28 capacity reference.",
        "createdAt": authority["retrievedAt"],
        "operatorIdentifier": "repository-seed",
        "verificationStatus": "identity_and_capacity_reference_verified",
        "capacityReferenceId": authority["capacityReferenceId"],
        "capacityReferenceSha256": authority["capacityReferenceCanonicalSha256"],
        "stalenessThresholdStatus": "not_governed",
        "allocationStatus": "not_configured",
        "sourceReferences": references,
        "hospitals": hospitals,
    }


def write_official_inventory_seed(path: str | Path | None = None) -> dict[str, Any]:
    from hospital_inventory import SEED_PATH, validate_inventory

    target = Path(path) if path is not None else SEED_PATH
    value = build_official_inventory_seed()
    validate_inventory(value)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return value
