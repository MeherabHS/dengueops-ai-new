from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from hospital_inventory import SEED_PATH, load_inventory  # noqa: E402
from runtime_hospital_inventory_commit import (  # noqa: E402
    HospitalInventoryCommitError,
    activate_inventory,
    import_inventory,
)
from runtime_hospital_inventory_verify import (  # noqa: E402
    HospitalInventoryVerificationError,
    list_inventory_versions,
    verify_active_inventory,
    verify_inventory_version,
)


def seed_metadata() -> tuple[str, str]:
    seed = load_inventory()
    return seed["operatorIdentifier"], seed["changeReason"]


def import_seed(runtime: Path) -> dict:
    operator, reason = seed_metadata()
    return import_inventory(runtime, SEED_PATH, operator_identifier=operator, change_reason=reason)


def write_second_seed(path: Path) -> dict:
    inventory = copy.deepcopy(load_inventory())
    inventory["inventoryId"] = "dhaka-government-hospitals-20260728-v2"
    inventory["inventoryVersion"] = "1.0.1"
    inventory["changeReason"] = "Deactivate one hospital in an immutable test version."
    inventory["operatorIdentifier"] = "test-operator"
    inventory["hospitals"][0]["active"] = False
    path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    return inventory


def write_inventory_version(
    path: Path,
    inventory: dict,
    *,
    inventory_id: str,
    inventory_version: str,
    change_reason: str,
) -> dict:
    value = copy.deepcopy(inventory)
    value["inventoryId"] = inventory_id
    value["inventoryVersion"] = inventory_version
    value["changeReason"] = change_reason
    value["operatorIdentifier"] = "acceptance-operator"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value


def test_import_is_append_only_and_never_activates(tmp_path: Path) -> None:
    runtime = tmp_path.resolve()
    result = import_seed(runtime)
    assert result["activated"] is False
    assert not (runtime / "deployments/dhaka_south/hospital-inventory/latest.json").exists()
    assert verify_inventory_version(runtime, result["inventoryId"])["inventory"]["inventoryId"] == result["inventoryId"]
    with pytest.raises(HospitalInventoryCommitError, match="already exists"):
        import_seed(runtime)
    assert list_inventory_versions(runtime) == [result["inventoryId"]]


def test_explicit_activation_and_rollback_preserve_versions(tmp_path: Path) -> None:
    runtime = tmp_path.resolve()
    first = import_seed(runtime)
    first_pointer = activate_inventory(runtime, first["inventoryId"], operator_identifier="test-operator", activation_reason="Approve first test inventory.")
    second_path = tmp_path / "second.json"
    second = write_second_seed(second_path)
    import_inventory(runtime, second_path, operator_identifier=second["operatorIdentifier"], change_reason=second["changeReason"])
    second_pointer = activate_inventory(runtime, second["inventoryId"], operator_identifier="test-operator", activation_reason="Approve second test inventory.")
    assert second_pointer["previousInventoryId"] == first["inventoryId"]
    second_pointer_bytes = (runtime / "deployments/dhaka_south/hospital-inventory/latest.json").read_bytes()
    rollback = activate_inventory(runtime, first["inventoryId"], operator_identifier="test-operator", activation_reason="Rollback test.")
    assert rollback["inventoryId"] == first["inventoryId"]
    assert rollback["previousInventoryId"] == second["inventoryId"]
    assert rollback["previousPointerSha256"] == hashlib.sha256(second_pointer_bytes).hexdigest()
    assert first_pointer["inventoryId"] in list_inventory_versions(runtime)
    assert second["inventoryId"] in list_inventory_versions(runtime)
    assert verify_active_inventory(runtime)["inventory"]["inventoryId"] == first["inventoryId"]


def test_tamper_missing_artifact_and_wrong_hash_fail(tmp_path: Path) -> None:
    runtime = tmp_path.resolve()
    imported = import_seed(runtime)
    package = runtime / "hospital-inventories" / imported["inventoryId"]
    artifact = package / "artifacts/hospital_inventory.json"
    original = artifact.read_bytes()
    artifact.write_bytes(original + b" ")
    with pytest.raises(HospitalInventoryVerificationError):
        verify_inventory_version(runtime, imported["inventoryId"])
    artifact.write_bytes(original)
    artifact.unlink()
    with pytest.raises(HospitalInventoryVerificationError):
        verify_inventory_version(runtime, imported["inventoryId"])


def test_failed_import_and_failed_activation_leave_pointer_unchanged(tmp_path: Path) -> None:
    runtime = tmp_path.resolve()
    imported = import_seed(runtime)
    activate_inventory(runtime, imported["inventoryId"], operator_identifier="test-operator", activation_reason="Initial test activation.")
    pointer_path = runtime / "deployments/dhaka_south/hospital-inventory/latest.json"
    before = pointer_path.read_bytes()
    invalid = copy.deepcopy(load_inventory())
    invalid["inventoryId"] = "invalid-next-version"
    invalid["operatorIdentifier"] = "test-operator"
    invalid["changeReason"] = "Invalid test import."
    invalid["hospitals"][0]["resources"][0]["quantity"] = -1
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError):
        import_inventory(runtime, invalid_path, operator_identifier="test-operator", change_reason="Invalid test import.")
    with pytest.raises(HospitalInventoryVerificationError):
        activate_inventory(runtime, "missing-inventory", operator_identifier="test-operator", activation_reason="Must fail.")
    assert pointer_path.read_bytes() == before


def test_operator_and_reason_are_required(tmp_path: Path) -> None:
    operator, reason = seed_metadata()
    with pytest.raises(HospitalInventoryCommitError):
        import_inventory(tmp_path.resolve(), SEED_PATH, operator_identifier="", change_reason=reason)
    imported = import_inventory(tmp_path.resolve(), SEED_PATH, operator_identifier=operator, change_reason=reason)
    with pytest.raises(HospitalInventoryCommitError):
        activate_inventory(tmp_path.resolve(), imported["inventoryId"], operator_identifier="", activation_reason="reason")


def test_governed_add_update_deactivate_workflow_preserves_every_version(tmp_path: Path) -> None:
    runtime = (tmp_path / "runtime-authority").resolve()
    operator = "acceptance-operator"
    original = load_inventory()

    added = copy.deepcopy(original["hospitals"][0])
    added["hospitalId"] = "acceptance-fixture-hospital"
    added["officialName"] = "Acceptance Fixture Government Hospital"
    with_addition = copy.deepcopy(original)
    with_addition["hospitals"].append(added)
    add_path = tmp_path / "add.json"
    add_reason = "Acceptance fixture: add a governed hospital identity."
    added_inventory = write_inventory_version(
        add_path,
        with_addition,
        inventory_id="acceptance-inventory-v1",
        inventory_version="1.0.0",
        change_reason=add_reason,
    )
    imported_add = import_inventory(runtime, add_path, operator_identifier=operator, change_reason=add_reason)
    add_artifact = runtime / "hospital-inventories" / imported_add["inventoryId"] / "artifacts/hospital_inventory.json"
    add_bytes = add_artifact.read_bytes()

    with_update = copy.deepcopy(added_inventory)
    resource = with_update["hospitals"][0]["resources"][0]
    resource.update(quantity=25, dataStatus="verified", asOf="2026-07-28T00:00:00Z")
    update_path = tmp_path / "update.json"
    update_reason = "Acceptance fixture: update a governed resource value."
    updated_inventory = write_inventory_version(
        update_path,
        with_update,
        inventory_id="acceptance-inventory-v2",
        inventory_version="1.0.1",
        change_reason=update_reason,
    )
    imported_update = import_inventory(runtime, update_path, operator_identifier=operator, change_reason=update_reason)

    with_deactivation = copy.deepcopy(updated_inventory)
    next(item for item in with_deactivation["hospitals"] if item["hospitalId"] == added["hospitalId"])["active"] = False
    deactivate_path = tmp_path / "deactivate.json"
    deactivate_reason = "Acceptance fixture: deactivate a governed hospital without deletion."
    deactivated_inventory = write_inventory_version(
        deactivate_path,
        with_deactivation,
        inventory_id="acceptance-inventory-v3",
        inventory_version="1.0.2",
        change_reason=deactivate_reason,
    )
    imported_deactivate = import_inventory(
        runtime,
        deactivate_path,
        operator_identifier=operator,
        change_reason=deactivate_reason,
    )

    assert all(result["activated"] is False for result in (imported_add, imported_update, imported_deactivate))
    assert not (runtime / "deployments/dhaka_south/hospital-inventory/latest.json").exists()
    assert list_inventory_versions(runtime) == [
        "acceptance-inventory-v1",
        "acceptance-inventory-v2",
        "acceptance-inventory-v3",
    ]

    verified_add = verify_inventory_version(runtime, imported_add["inventoryId"])
    verified_update = verify_inventory_version(runtime, imported_update["inventoryId"])
    verified_deactivate = verify_inventory_version(runtime, imported_deactivate["inventoryId"])
    assert any(item["hospitalId"] == added["hospitalId"] for item in verified_add["inventory"]["hospitals"])
    assert verified_update["inventory"]["hospitals"][0]["resources"][0]["quantity"] == 25
    assert next(
        item for item in verified_deactivate["inventory"]["hospitals"] if item["hospitalId"] == added["hospitalId"]
    )["active"] is False

    # Publishing later changes cannot rewrite the earlier immutable artifact.
    assert add_artifact.read_bytes() == add_bytes
    assert verified_add["inventory"]["hospitals"][0]["resources"][0]["quantity"] is None
    assert verified_add["inventoryArtifactSha256"] != verified_update["inventoryArtifactSha256"]
    assert verified_update["inventoryArtifactSha256"] != verified_deactivate["inventoryArtifactSha256"]
