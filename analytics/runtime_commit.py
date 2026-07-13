"""Validate and atomically commit an isolated P1.4C-2 Quick Forecast run."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from runtime_context import require_absolute_directory, require_within


ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = {
    "metadata/run.json": "runtime_run.schema.json",
    "artifacts/forecast_output.json": "runtime_forecast_output.schema.json",
    "artifacts/forecast_uncertainty.json": "runtime_forecast_uncertainty.schema.json",
    "artifacts/dashboard_summary.json": "runtime_dashboard_summary.schema.json",
    "artifacts/model_card.json": "runtime_model_card.schema.json",
}
REQUIRED_ARTIFACTS = {
    "input_manifest.json", "model_features.csv", "forecast_output.json",
    "forecast_uncertainty.json", "model_card.json", "dashboard_summary.json",
    "chart_data.json", "pipeline_run_summary.json",
}
PROHIBITED_ARTIFACTS = {
    "candidate_model_comparison.json", "rolling_validation.json", "directives.json",
    "preparedness.json", "facility_projections.json", "inventory_alerts.json",
}


class RuntimeCommitError(RuntimeError):
    """Raised when a runtime run cannot be safely committed."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeCommitError(f"Invalid runtime JSON: {path.name}.") from exc
    if not isinstance(value, dict):
        raise RuntimeCommitError(f"Runtime JSON must be an object: {path.name}.")
    return value


def _validate_schema(path: Path, schema_name: str) -> dict[str, Any]:
    value = _load_json(path)
    schema = json.loads((ROOT / "config" / schema_name).read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        raise RuntimeCommitError(f"{path.name} failed its runtime schema: {errors[0].message}")
    return value


def _acquire_lock(path: Path, timeout_seconds: float = 30.0) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeCommitError("Deployment commit lock timed out.")
            time.sleep(0.1)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _make_immutable(root: Path) -> None:
    if os.name == "nt":
        return
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def commit_runtime_run(runtime_root: Path, staging_path: Path, job: dict[str, Any]) -> dict[str, Any]:
    runtime_root = require_absolute_directory(runtime_root, "runtime root")
    staging_root = require_within(runtime_root, staging_path, "staging run")
    expected_staging_parent = (runtime_root / "staging").resolve()
    if staging_root.parent != expected_staging_parent or staging_root.name != job.get("runId"):
        raise RuntimeCommitError("Staging identity does not match the job.")
    artifacts = staging_root / "artifacts"
    metadata = staging_root / "metadata"
    present = {path.name for path in artifacts.iterdir()} if artifacts.exists() else set()
    missing = REQUIRED_ARTIFACTS - present
    prohibited = PROHIBITED_ARTIFACTS & present
    if missing:
        raise RuntimeCommitError(f"Runtime artifact bundle is incomplete: {sorted(missing)}")
    if prohibited:
        raise RuntimeCommitError(f"Prohibited runtime artifacts are present: {sorted(prohibited)}")

    values = {relative: _validate_schema(staging_root / relative, schema) for relative, schema in SCHEMAS.items()}
    run = values["metadata/run.json"]
    forecast = values["artifacts/forecast_output.json"]
    uncertainty = values["artifacts/forecast_uncertainty.json"]
    dashboard = values["artifacts/dashboard_summary.json"]
    card = values["artifacts/model_card.json"]
    identities = (job["runId"], job["jobId"], job["datasetId"], job["deploymentId"])
    for value in (run, forecast, uncertainty, card):
        if tuple(value.get(key) for key in ("runId", "jobId", "datasetId", "deploymentId")) != identities:
            raise RuntimeCommitError("Runtime artifact identity mismatch.")
    if dashboard.get("run", {}).get("runId") != job["runId"] or dashboard.get("run", {}).get("datasetId") != job["datasetId"]:
        raise RuntimeCommitError("Runtime dashboard identity mismatch.")
    if any(uncertainty.get(field) is not None for field in ("lowerRaw", "upperRaw", "lowerReported", "upperReported", "nominalCoverage", "historicalCoverage")):
        raise RuntimeCommitError("Uploaded Quick Forecast uncertainty must not contain inherited bounds or coverage.")
    if uncertainty.get("bundledP13RangeReused") is not False or uncertainty.get("rmseFallbackAllowed") is not False:
        raise RuntimeCommitError("Synthetic uncertainty reuse or RMSE fallback is prohibited.")
    if dashboard.get("preparedness") != {
        "availabilityStatus": "unavailable_missing_planning_policy", "scenarios": None,
        "counts": None, "facilities": [], "alerts": [],
    }:
        raise RuntimeCommitError("Runtime preparedness must remain unavailable and empty.")

    artifact_hashes = {name: sha256_file(artifacts / name) for name in sorted(REQUIRED_ARTIFACTS)}
    expected_card_hashes = card.get("artifactHashes", {})
    for name, digest in artifact_hashes.items():
        if name != "model_card.json" and expected_card_hashes.get(name) != digest:
            raise RuntimeCommitError(f"Model-card artifact hash mismatch: {name}.")
    sequence = run.get("artifactPublicationSequence", [])
    if not sequence or sequence[-1] != "model_card.json":
        raise RuntimeCommitError("The runtime model card was not published last.")

    committed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    commit = {
        "schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"],
        "workspaceId": job["workspaceId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast",
        "sourceType": "uploaded", "status": "committed", "policySha256": job["policySha256"],
        "artifactHashes": artifact_hashes, "modelCardPublishedLast": True,
        "prohibitedArtifactsAbsent": True, "committedAt": committed_at,
    }
    commit_schema = json.loads((ROOT / "config" / "runtime_commit.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(commit_schema, format_checker=FormatChecker()).validate(commit)
    atomic_json(metadata / "commit.json", commit)

    runs_root = (runtime_root / "runs").resolve()
    runs_root.mkdir(parents=True, exist_ok=True)
    committed_root = runs_root / job["runId"]
    if committed_root.exists():
        raise RuntimeCommitError("The immutable runtime run already exists.")
    os.replace(staging_root, committed_root)
    _fsync_directory(runs_root)
    _make_immutable(committed_root)

    deployment_root = runtime_root / "deployments" / job["deploymentId"]
    lock_path = deployment_root / "locks" / "commit.lock"
    descriptor = _acquire_lock(lock_path)
    try:
        committed_card = committed_root / "artifacts" / "model_card.json"
        committed_dashboard = committed_root / "artifacts" / "dashboard_summary.json"
        committed_commit = committed_root / "metadata" / "commit.json"
        if sha256_file(committed_card) != artifact_hashes["model_card.json"]:
            raise RuntimeCommitError("Committed model card changed before pointer publication.")
        pointer = {
            "schemaVersion": "1.0", "deploymentId": job["deploymentId"], "runId": job["runId"],
            "datasetId": job["datasetId"], "workflowMode": "quick_forecast", "sourceType": "uploaded",
            "committedAt": committed_at, "modelCardSha256": sha256_file(committed_card),
            "dashboardSummarySha256": sha256_file(committed_dashboard),
            "commitRecordSha256": sha256_file(committed_commit),
        }
        latest_schema = json.loads((ROOT / "config" / "runtime_latest.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(latest_schema, format_checker=FormatChecker()).validate(pointer)
        deployment_root.mkdir(parents=True, exist_ok=True)
        atomic_json(deployment_root / "latest.json", pointer)
        _fsync_directory(deployment_root)
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)
    return {"runRoot": str(committed_root), "pointer": pointer, "commit": commit}
