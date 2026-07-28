"""Reopen and verify immutable hospital inventory packages and pointers."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from hospital_inventory import (
    HospitalInventoryError,
    canonical_json_sha256,
    load_inventory,
    source_reference_snapshot,
)

ROOT = Path(__file__).resolve().parent.parent
COMMIT_SCHEMA = ROOT / "config" / "runtime_hospital_inventory_commit.schema.json"
LATEST_SCHEMA = ROOT / "config" / "runtime_hospital_inventory_latest.schema.json"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")


class HospitalInventoryVerificationError(ValueError):
    """Raised when immutable inventory authority does not verify."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _root(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise HospitalInventoryVerificationError("Runtime root must be absolute.")
    return root.resolve()


def _within(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root not in path.parents:
        raise HospitalInventoryVerificationError("Inventory path escaped runtime root.")
    return path


def _validated_json(path: Path, schema_path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HospitalInventoryVerificationError("Inventory authority file is unreadable.") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise HospitalInventoryVerificationError(f"Inventory authority failed schema validation: {errors[0].message}")
    return value


def verify_inventory_version(runtime_root: str | Path, inventory_id: str) -> dict[str, Any]:
    root = _root(runtime_root)
    if not SAFE_ID.fullmatch(inventory_id):
        raise HospitalInventoryVerificationError("Invalid inventory ID.")
    package = _within(root, f"hospital-inventories/{inventory_id}")
    artifact = package / "artifacts" / "hospital_inventory.json"
    commit_path = package / "metadata" / "commit.json"
    references_path = package / "metadata" / "source_references.json"
    commit = _validated_json(commit_path, COMMIT_SCHEMA)
    try:
        inventory = load_inventory(artifact)
        references = json.loads(references_path.read_text(encoding="utf-8"))
    except (HospitalInventoryError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HospitalInventoryVerificationError("Inventory artifact or references failed verification.") from exc
    expected_artifact = f"hospital-inventories/{inventory_id}/artifacts/hospital_inventory.json"
    expected_references = f"hospital-inventories/{inventory_id}/metadata/source_references.json"
    checks = (
        (commit["inventoryId"], inventory_id),
        (inventory["inventoryId"], inventory_id),
        (commit["inventoryVersion"], inventory["inventoryVersion"]),
        (commit["inventoryArtifactPath"], expected_artifact),
        (commit["sourceReferencesPath"], expected_references),
        (commit["inventoryCanonicalSha256"], canonical_json_sha256(inventory)),
        (commit["inventoryRawSha256"], _sha(artifact)),
        (commit["sourceReferencesSha256"], _sha(references_path)),
        (references, source_reference_snapshot(inventory)),
    )
    if any(actual != expected for actual, expected in checks):
        raise HospitalInventoryVerificationError("Immutable inventory commit binding mismatch.")
    return {
        "inventory": inventory,
        "commit": commit,
        "inventoryArtifactSha256": _sha(artifact),
        "inventoryCommitSha256": _sha(commit_path),
        "packagePath": package,
    }


def verify_active_inventory(runtime_root: str | Path, deployment_id: str = "dhaka_south") -> dict[str, Any]:
    root = _root(runtime_root)
    if deployment_id != "dhaka_south":
        raise HospitalInventoryVerificationError("Unsupported inventory deployment.")
    latest_path = _within(root, "deployments/dhaka_south/hospital-inventory/latest.json")
    pointer = _validated_json(latest_path, LATEST_SCHEMA)
    verified = verify_inventory_version(root, pointer["inventoryId"])
    artifact_path = _within(root, pointer["inventoryArtifactPath"])
    commit_path = _within(root, pointer["inventoryCommitPath"])
    activation_path = _within(root, pointer["activationRecordPath"])
    if (
        pointer["inventoryArtifactSha256"] != _sha(artifact_path)
        or pointer["inventoryCommitSha256"] != _sha(commit_path)
        or pointer["activationRecordSha256"] != _sha(activation_path)
        or verified["inventoryArtifactSha256"] != pointer["inventoryArtifactSha256"]
        or verified["inventoryCommitSha256"] != pointer["inventoryCommitSha256"]
    ):
        raise HospitalInventoryVerificationError("Active inventory pointer hash mismatch.")
    try:
        activation = json.loads(activation_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HospitalInventoryVerificationError("Inventory activation record is unreadable.") from exc
    expected_activation = {
        "schemaVersion": "1.0",
        "activationId": pointer["activationId"],
        "deploymentId": pointer["deploymentId"],
        "inventoryId": pointer["inventoryId"],
        "inventoryArtifactSha256": pointer["inventoryArtifactSha256"],
        "inventoryCommitSha256": pointer["inventoryCommitSha256"],
        "previousPointerSha256": pointer["previousPointerSha256"],
        "previousInventoryId": pointer["previousInventoryId"],
        "activationOperator": pointer["activationOperator"],
        "activationReason": pointer["activationReason"],
        "activatedAt": pointer["activatedAt"],
    }
    if activation != expected_activation:
        raise HospitalInventoryVerificationError("Inventory activation record binding mismatch.")
    return {"pointer": pointer, **verified}


def list_inventory_versions(runtime_root: str | Path) -> list[str]:
    root = _root(runtime_root)
    versions = _within(root, "hospital-inventories")
    if not versions.exists():
        return []
    result = []
    for path in versions.iterdir():
        if path.is_dir() and SAFE_ID.fullmatch(path.name):
            verify_inventory_version(root, path.name)
            result.append(path.name)
    return sorted(result)
