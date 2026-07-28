"""Atomic append-only publication and explicit activation of hospital inventory."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from hospital_inventory import (
    canonical_json_sha256,
    load_inventory,
    source_reference_snapshot,
)
from runtime_hospital_inventory_verify import verify_active_inventory, verify_inventory_version

ROOT = Path(__file__).resolve().parent.parent
COMMIT_SCHEMA = ROOT / "config" / "runtime_hospital_inventory_commit.schema.json"
LATEST_SCHEMA = ROOT / "config" / "runtime_hospital_inventory_latest.schema.json"


class HospitalInventoryCommitError(RuntimeError):
    """Raised when inventory cannot be safely published or activated."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_root(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise HospitalInventoryCommitError("Runtime root must be absolute.")
    return path.resolve()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _validate(value: dict[str, Any], schema_path: Path) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise HospitalInventoryCommitError(f"Runtime inventory metadata failed schema validation: {errors[0].message}")


def import_inventory(
    runtime_root: str | Path,
    inventory_path: str | Path,
    *,
    operator_identifier: str,
    change_reason: str,
) -> dict[str, Any]:
    if not operator_identifier.strip() or len(operator_identifier) > 128:
        raise HospitalInventoryCommitError("Import requires a bounded operator identifier.")
    if not change_reason.strip() or len(change_reason) > 1000:
        raise HospitalInventoryCommitError("Import requires a bounded change reason.")
    root = _runtime_root(runtime_root)
    inventory = load_inventory(inventory_path)
    if inventory["operatorIdentifier"] != operator_identifier or inventory["changeReason"] != change_reason:
        raise HospitalInventoryCommitError("Import operator/reason must match reviewed inventory metadata.")
    inventory_id = inventory["inventoryId"]
    final = root / "hospital-inventories" / inventory_id
    if final.exists():
        raise HospitalInventoryCommitError("Immutable inventory ID already exists.")
    staging_parent = root / "inventory-staging"
    staging = staging_parent / f"{inventory_id}-{uuid.uuid4()}"
    try:
        artifacts, metadata = staging / "artifacts", staging / "metadata"
        artifacts.mkdir(parents=True)
        metadata.mkdir(parents=True)
        _atomic_json(artifacts / "hospital_inventory.json", inventory)
        _atomic_json(metadata / "source_references.json", source_reference_snapshot(inventory))
        published_at = _now()
        commit = {
            "schemaVersion": "1.0",
            "inventoryId": inventory_id,
            "inventoryVersion": inventory["inventoryVersion"],
            "deploymentId": inventory["deploymentId"],
            "deploymentDisplayName": inventory["deploymentDisplayName"],
            "inventoryCanonicalSha256": canonical_json_sha256(inventory),
            "inventoryRawSha256": _sha(artifacts / "hospital_inventory.json"),
            "inventoryArtifactPath": f"hospital-inventories/{inventory_id}/artifacts/hospital_inventory.json",
            "sourceReferencesSha256": _sha(metadata / "source_references.json"),
            "sourceReferencesPath": f"hospital-inventories/{inventory_id}/metadata/source_references.json",
            "operatorIdentifier": operator_identifier,
            "changeReason": change_reason,
            "verificationStatus": inventory["verificationStatus"],
            "publishedAt": published_at,
        }
        _validate(commit, COMMIT_SCHEMA)
        _atomic_json(metadata / "commit.json", commit)
        # Reopen every staged artifact before its append-only rename.
        load_inventory(artifacts / "hospital_inventory.json")
        if json.loads((metadata / "source_references.json").read_text(encoding="utf-8")) != source_reference_snapshot(inventory):
            raise HospitalInventoryCommitError("Staged source references changed.")
        final.parent.mkdir(parents=True, exist_ok=True)
        if final.exists():
            raise HospitalInventoryCommitError("Immutable inventory ID already exists.")
        os.replace(staging, final)
        verified = verify_inventory_version(root, inventory_id)
        return {
            "inventoryId": inventory_id,
            "inventoryArtifactSha256": verified["inventoryArtifactSha256"],
            "inventoryCommitSha256": verified["inventoryCommitSha256"],
            "activated": False,
        }
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def activate_inventory(
    runtime_root: str | Path,
    inventory_id: str,
    *,
    operator_identifier: str,
    activation_reason: str,
) -> dict[str, Any]:
    if not operator_identifier.strip() or len(operator_identifier) > 128:
        raise HospitalInventoryCommitError("Activation requires a bounded operator identifier.")
    if not activation_reason.strip() or len(activation_reason) > 1000:
        raise HospitalInventoryCommitError("Activation requires a bounded reason.")
    root = _runtime_root(runtime_root)
    verified = verify_inventory_version(root, inventory_id)
    authority_root = root / "deployments" / "dhaka_south" / "hospital-inventory"
    lock_path = authority_root / "locks" / "activation.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HospitalInventoryCommitError("Inventory activation is already in progress.") from exc
    try:
        latest_path = authority_root / "latest.json"
        previous_bytes = latest_path.read_bytes() if latest_path.exists() else None
        previous = json.loads(previous_bytes.decode("utf-8")) if previous_bytes is not None else None
        previous_sha = hashlib.sha256(previous_bytes).hexdigest() if previous_bytes is not None else None
        activation_id, activated_at = str(uuid.uuid4()), _now()
        activation = {
            "schemaVersion": "1.0",
            "activationId": activation_id,
            "deploymentId": "dhaka_south",
            "inventoryId": inventory_id,
            "inventoryArtifactSha256": verified["inventoryArtifactSha256"],
            "inventoryCommitSha256": verified["inventoryCommitSha256"],
            "previousPointerSha256": previous_sha,
            "previousInventoryId": previous.get("inventoryId") if isinstance(previous, dict) else None,
            "activationOperator": operator_identifier,
            "activationReason": activation_reason,
            "activatedAt": activated_at,
        }
        activation_relative = f"deployments/dhaka_south/hospital-inventory/activations/{activation_id}.json"
        activation_path = root / activation_relative
        _atomic_json(activation_path, activation)
        pointer = {
            "schemaVersion": "1.0",
            "deploymentId": "dhaka_south",
            "deploymentDisplayName": "Dhaka",
            "inventoryId": inventory_id,
            "inventoryArtifactPath": verified["commit"]["inventoryArtifactPath"],
            "inventoryArtifactSha256": verified["inventoryArtifactSha256"],
            "inventoryCommitPath": f"hospital-inventories/{inventory_id}/metadata/commit.json",
            "inventoryCommitSha256": verified["inventoryCommitSha256"],
            "activationId": activation_id,
            "activationRecordPath": activation_relative,
            "activationRecordSha256": _sha(activation_path),
            "previousPointerSha256": previous_sha,
            "previousInventoryId": activation["previousInventoryId"],
            "activationOperator": operator_identifier,
            "activationReason": activation_reason,
            "activatedAt": activated_at,
        }
        _validate(pointer, LATEST_SCHEMA)
        _atomic_json(latest_path, pointer)
        return verify_active_inventory(root)["pointer"]
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)
