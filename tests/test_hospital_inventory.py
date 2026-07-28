from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from hospital_inventory import HospitalInventoryError, inventory_diff, load_inventory, validate_inventory  # noqa: E402


def test_seed_has_official_identities_and_unknown_resources() -> None:
    inventory = load_inventory()
    assert inventory["inventoryId"] == "dhaka-government-hospitals-20260729-v3"
    assert inventory["inventoryVersion"] == "3.0.0"
    assert len(inventory["hospitals"]) == 41
    assert inventory["allocationStatus"] == "not_configured"
    assert inventory["stalenessThresholdStatus"] == "not_governed"
    assert all(reference["sourceUrl"].startswith("https://") for reference in inventory["sourceReferences"])
    assert all(hospital["ownership"] in {"public_government", "government_autonomous"} for hospital in inventory["hospitals"])
    assert all(hospital["allocationShare"] == {"status": "not_configured", "value": None} for hospital in inventory["hospitals"])
    participating = [hospital for hospital in inventory["hospitals"] if hospital["participationStatus"] == "included"]
    assert len(participating) == 13
    assert {hospital["hospitalId"] for hospital in participating} == {
        "mugda-medical-college-hospital",
        "dhaka-medical-college-hospital",
        "dncc-dedicated-specialized-hospital",
        "shaheed-suhrawardy-medical-college-hospital",
        "bangladesh-medical-university",
        "sir-salimullah-medical-college-mitford-hospital",
        "kurmitola-general-hospital",
        "railway-general-hospital-kamalapur",
        "lalkuthi-maternal-child-health-institute",
        "kamrangirchar-31-bed-hospital",
        "aminbazar-20-bed-government-hospital",
        "bangladesh-shishu-hospital-institute",
        "institute-child-mother-health-matuail",
    }
    assert all(hospital["active"] and hospital["managementDecisionStatus"] == "pending_review" for hospital in participating)
    assert all(hospital["currentAvailableBeds"] is None for hospital in inventory["hospitals"])
    resources = [resource for hospital in inventory["hospitals"] for resource in hospital["resources"]]
    available = [resource for resource in resources if resource["resourceType"] == "available_beds"]
    assert available and all(resource["quantity"] is None and resource["dataStatus"] == "unknown" for resource in available)
    assert all(resource["availabilityStatus"] == "not_known" for resource in resources)
    serialized = str(inventory)
    assert "Synthetic Benchmark Facility" not in serialized
    assert "INV-F" not in serialized


def test_historical_v2_inventory_contract_remains_readable() -> None:
    inventory = load_inventory()
    inventory["inventoryId"] = "historical-inventory-v2"
    inventory["inventoryVersion"] = "2.0.0"
    for hospital in inventory["hospitals"]:
        for field in (
            "participationStatus",
            "managementDecisionStatus",
            "selectedBedCapacity",
            "currentAvailableBeds",
        ):
            hospital.pop(field)
    assert validate_inventory(inventory)["inventoryVersion"] == "2.0.0"


def test_zero_is_known_and_null_is_unknown() -> None:
    inventory = load_inventory()
    resource = inventory["hospitals"][0]["resources"][0]
    resource.update(quantity=0, dataStatus="verified_capacity_reference", asOf="2026-07-28T00:00:00Z")
    assert validate_inventory(inventory)["hospitals"][0]["resources"][0]["quantity"] == 0
    resource.update(quantity=None, dataStatus="verified_capacity_reference")
    with pytest.raises(HospitalInventoryError):
        validate_inventory(inventory)


def test_duplicate_ids_and_active_names_fail() -> None:
    inventory = load_inventory()
    duplicate_id = copy.deepcopy(inventory["hospitals"][0])
    duplicate_id["officialName"] = "Distinct Official Name"
    inventory["hospitals"].append(duplicate_id)
    with pytest.raises(HospitalInventoryError, match="Duplicate hospital ID"):
        validate_inventory(inventory)
    inventory = load_inventory()
    duplicate_name = copy.deepcopy(inventory["hospitals"][0])
    duplicate_name["hospitalId"] = "distinct-id"
    duplicate_name["officialName"] = f"  {duplicate_name['officialName'].upper()}  "
    inventory["hospitals"].append(duplicate_name)
    with pytest.raises(HospitalInventoryError, match="Duplicate normalized"):
        validate_inventory(inventory)


def test_deactivation_and_diff_are_non_destructive() -> None:
    before, after = load_inventory(), copy.deepcopy(load_inventory())
    after["inventoryId"] = "dhaka-government-hospitals-20260729-v4"
    after["inventoryVersion"] = "3.0.1"
    after["hospitals"][0]["active"] = False
    assert validate_inventory(after)["hospitals"][0]["active"] is False
    assert inventory_diff(before, after)["deactivatedHospitalIds"] == [before["hospitals"][0]["hospitalId"]]


def test_invalid_resource_coordinates_references_and_allocation_fail() -> None:
    inventory = load_inventory()
    inventory["hospitals"][0]["resources"][0]["quantity"] = -1
    with pytest.raises(HospitalInventoryError):
        validate_inventory(inventory)
    inventory = load_inventory()
    inventory["hospitals"][0]["location"]["coordinates"] = {"latitude": 91, "longitude": 90}
    with pytest.raises(HospitalInventoryError):
        validate_inventory(inventory)
    inventory = load_inventory()
    inventory["hospitals"][0]["identityVerification"]["verificationReferenceId"] = "missing"
    with pytest.raises(HospitalInventoryError, match="unknown identity"):
        validate_inventory(inventory)
    inventory = load_inventory()
    inventory["hospitals"][0]["allocationShare"] = {"status": "configured", "value": "1.000000"}
    with pytest.raises(HospitalInventoryError, match="Unconfigured allocation"):
        validate_inventory(inventory)
