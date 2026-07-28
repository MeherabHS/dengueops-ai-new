"""Append-only publication for synthetic hospital-preparedness qualification."""
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

from formula_policy import load_qualification_formula_policy, resolve_qualification_formula
from formula_registry import load_governed_formula_registry
from hospital_capacity_reference import load_capacity_reference
from hospital_inventory import load_inventory
from hospital_preparedness_source import resolve_current_quick_forecast
from runtime_hospital_preparedness import build_preparedness_evidence
from synthetic_hospital_inventory import load_scenario_policy, load_synthetic_inventory

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_SCHEMA = ROOT / "config" / "runtime_hospital_preparedness.schema.json"
COMMIT_SCHEMA = ROOT / "config" / "runtime_hospital_preparedness_commit.schema.json"
LATEST_SCHEMA = ROOT / "config" / "runtime_hospital_preparedness_latest.schema.json"


class HospitalPreparednessCommitError(RuntimeError):
    """Raised when qualification publication cannot complete atomically."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write((json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
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
        raise HospitalPreparednessCommitError(f"Qualification schema failure: {errors[0].message}")


def _safe_runtime_root(value: str | Path) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise HospitalPreparednessCommitError("Runtime root must be absolute.")
    return root.resolve()


def publish_qualification(
    runtime_root: str | Path,
    scenario_id: str,
    *,
    preparedness_id: str | None = None,
) -> dict[str, Any]:
    root = _safe_runtime_root(runtime_root)
    evidence_id = preparedness_id or str(uuid.uuid4())
    try:
        uuid.UUID(evidence_id)
    except ValueError as exc:
        raise HospitalPreparednessCommitError("Preparedness ID must be a UUID.") from exc
    final = root / "hospital-preparedness-qualification" / evidence_id
    if final.exists():
        raise HospitalPreparednessCommitError("Immutable qualification ID already exists.")
    source = resolve_current_quick_forecast(root)
    capacity = load_capacity_reference()
    official_inventory = load_inventory()
    synthetic_inventory = load_synthetic_inventory()
    scenario_policy = load_scenario_policy()
    registry = load_governed_formula_registry()
    formula_policy = load_qualification_formula_policy()
    formula = resolve_qualification_formula("inventory.gap", requested_evidence_scope="synthetic_qualification")
    generated_at = _now()
    evidence = build_preparedness_evidence(source, scenario_id, evidence_id, generated_at)
    allocation = {
        "schemaVersion": "1.0",
        "allocationMethod": synthetic_inventory["allocationMethod"],
        "operationalAllocationApproved": False,
        "scenarioId": scenario_id,
        "includedHospitalSet": [
            {"hospitalId": row["hospitalId"], "allocationShare": row["allocationShare"]}
            for row in next(item for item in synthetic_inventory["scenarios"] if item["scenarioId"] == scenario_id)["hospitals"]
            if row["allocationStatus"] == "configured"
        ],
        "officialCapacityReferenceSha256": capacity["capacityReferenceCanonicalSha256"],
    }
    artifacts = {
        "preparedness_evidence.json": evidence,
        "official_capacity_reference_snapshot.json": capacity,
        "official_hospital_inventory_snapshot.json": official_inventory,
        "synthetic_inventory_snapshot.json": synthetic_inventory,
        "synthetic_scenario_policy_snapshot.json": scenario_policy,
        "allocation_policy_snapshot.json": allocation,
        "formula_registry_snapshot.json": registry,
        "formula_snapshot.json": formula,
        "formula_activation_policy_snapshot.json": formula_policy,
        "forecast_commit_snapshot.json": source["bundle"]["commit"],
        "forecast_output_snapshot.json": source["bundle"]["forecast"],
        "forecast_uncertainty_snapshot.json": source["bundle"]["uncertainty"],
    }
    _validate(evidence, EVIDENCE_SCHEMA)
    staging = root / "hospital-preparedness-qualification-staging" / f"{evidence_id}-{uuid.uuid4()}"
    try:
        artifact_root = staging / "artifacts"
        artifact_root.mkdir(parents=True)
        for name, value in artifacts.items():
            _atomic_json(artifact_root / name, value)
        hashes = {name: _sha(artifact_root / name) for name in sorted(artifacts)}
        commit = {
            "schemaVersion": "1.0",
            "preparednessId": evidence_id,
            "scenarioId": scenario_id,
            "deploymentId": "dhaka_south",
            "evidenceScope": "synthetic_qualification",
            "forecastRunId": source["runId"],
            "forecastCommitSha256": source["commitSha256"],
            "artifactHashes": hashes,
            "publishedAt": generated_at,
        }
        _validate(commit, COMMIT_SCHEMA)
        _atomic_json(staging / "metadata" / "commit.json", commit)
        if final.exists():
            raise HospitalPreparednessCommitError("Immutable qualification ID already exists.")
        final.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, final)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    from runtime_hospital_preparedness_verify import verify_qualification
    verified = verify_qualification(root, evidence_id)
    pointer_root = root / "deployments" / "dhaka_south" / "hospital-preparedness-qualification"
    latest = pointer_root / "latest.json"
    lock = pointer_root / "locks" / "commit.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HospitalPreparednessCommitError("Qualification pointer update is already in progress.") from exc
    try:
        previous = latest.read_bytes() if latest.exists() else None
        pointer = {
            "schemaVersion": "1.0",
            "deploymentId": "dhaka_south",
            "evidenceScope": "synthetic_qualification",
            "preparednessId": evidence_id,
            "scenarioId": scenario_id,
            "evidencePath": f"hospital-preparedness-qualification/{evidence_id}/artifacts/preparedness_evidence.json",
            "evidenceSha256": verified["artifactHashes"]["preparedness_evidence.json"],
            "commitPath": f"hospital-preparedness-qualification/{evidence_id}/metadata/commit.json",
            "commitSha256": verified["commitSha256"],
            "previousPointerSha256": hashlib.sha256(previous).hexdigest() if previous else None,
            "advancedAt": _now(),
        }
        _validate(pointer, LATEST_SCHEMA)
        _atomic_json(latest, pointer)
    finally:
        os.close(descriptor)
        lock.unlink(missing_ok=True)
    return {"preparednessId": evidence_id, "scenarioId": scenario_id, "pointer": pointer}
