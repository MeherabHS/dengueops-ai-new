"""Validate and atomically commit an isolated P1.4C-2 Quick Forecast run."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import pandas as pd

from empirical_range import (
    METHOD_ID, METHOD_VERSION, NOMINAL_COVERAGE, REQUIRED_RESIDUALS, WARMUP_FOLDS,
    build_prequential_evaluation, build_runtime_fold_plan, construct_raw_interval,
    finite_sample_quantile,
)
from runtime_context import require_absolute_directory, require_within


ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = {
    "metadata/run.json": "runtime_run.schema.json",
    "artifacts/forecast_calibration.json": "runtime_forecast_calibration.schema.json",
    "artifacts/forecast_output.json": "runtime_forecast_output.schema.json",
    "artifacts/forecast_uncertainty.json": "runtime_forecast_uncertainty.schema.json",
    "artifacts/dashboard_summary.json": "runtime_dashboard_summary.schema.json",
    "artifacts/model_card.json": "runtime_model_card.schema.json",
}
REQUIRED_ARTIFACTS = {
    "input_manifest.json", "model_features.csv", "forecast_calibration.json", "forecast_output.json",
    "forecast_uncertainty.json", "model_card.json", "dashboard_summary.json",
    "chart_data.json", "pipeline_run_summary.json",
}
PUBLICATION_SEQUENCE = [
    "input_manifest.json", "model_features.csv", "forecast_calibration.json",
    "forecast_output.json", "forecast_uncertainty.json", "chart_data.json",
    "dashboard_summary.json", "pipeline_run_summary.json", "model_card.json",
]
PROHIBITED_ARTIFACTS = {
    "candidate_model_comparison.json", "rolling_validation.json", "directives.json",
    "preparedness.json", "facility_projections.json", "inventory_alerts.json",
}


class RuntimeCommitError(RuntimeError):
    """Raised when a runtime run cannot be safely committed."""


def json_sha(value: Mapping[str, Any]) -> str:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _close(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    try:
        return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return False


def _validate_calibration_bundle(
    artifacts: Path, forecast: dict[str, Any], calibration: dict[str, Any],
    uncertainty: dict[str, Any], dashboard: dict[str, Any], card: dict[str, Any],
    job: dict[str, Any],
) -> None:
    pipeline = _load_json(artifacts / "pipeline_run_summary.json")
    calibration_sha = sha256_file(artifacts / "forecast_calibration.json")
    if tuple(calibration.get(key) for key in ("runId", "jobId", "datasetId")) != (
        job["runId"], job["jobId"], job["datasetId"],
    ):
        raise RuntimeCommitError("Runtime calibration identity mismatch.")
    if (calibration.get("deploymentProfileId"), calibration.get("policyId"), calibration.get("policyVersion"), calibration.get("policySha256")) != (
        job["deploymentId"], job["policyId"], job["policyVersion"], job["policySha256"],
    ):
        raise RuntimeCommitError("Runtime calibration policy identity mismatch.")
    if (calibration.get("modelId"), calibration.get("modelParametersSha256"), calibration.get("candidateRegistrySha256")) != (
        forecast.get("activeModelId"), forecast.get("parameterHash"), forecast.get("candidateRegistrySha256"),
    ):
        raise RuntimeCommitError("Runtime calibration model identity mismatch.")
    if calibration.get("featureOrderSha256") != card.get("features", {}).get("orderSha256") \
            or calibration.get("featureOrderSha256") != forecast.get("trainingDataIdentity", {}).get("featureOrderSha256"):
        raise RuntimeCommitError("Runtime calibration feature-order identity mismatch.")
    if (calibration.get("targetColumn"), calibration.get("forecastHorizonWeeks")) != (forecast.get("target"), forecast.get("horizonWeeks")):
        raise RuntimeCommitError("Runtime calibration target identity mismatch.")
    if card.get("calibration", {}).get("artifactPath") != "artifacts/forecast_calibration.json" \
            or card.get("calibration", {}).get("artifactSha256") != calibration_sha:
        raise RuntimeCommitError("Runtime model card does not bind the calibration artifact.")
    if dashboard.get("evidence", {}).get("calibration") != {"path": "artifacts/forecast_calibration.json", "sha256": calibration_sha}:
        raise RuntimeCommitError("Runtime dashboard does not bind the calibration artifact.")

    frame = pd.read_csv(artifacts / "model_features.csv")
    expected_plan, expected_plan_sha = build_runtime_fold_plan(frame)
    if calibration.get("foldPlanSha256") != expected_plan_sha:
        raise RuntimeCommitError("Runtime calibration fold-plan hash mismatch.")
    status = calibration.get("calibrationStatus")
    if status == "available":
        if len(expected_plan) != REQUIRED_RESIDUALS or len(calibration.get("folds", [])) != REQUIRED_RESIDUALS:
            raise RuntimeCommitError("Available calibration requires exactly 68 governed folds.")
        residuals: list[dict[str, Any]] = []
        for expected, actual in zip(expected_plan, calibration["folds"]):
            public = {key: value for key, value in expected.items() if key not in {"trainEndExclusive", "embargoIndex", "validationIndex"}}
            if any(actual.get(key) != value for key, value in public.items()):
                raise RuntimeCommitError("Runtime calibration fold identity or matrix hash changed.")
            signed = float(actual["actualTarget"]) - float(actual["rawPrediction"])
            absolute = abs(signed)
            if not all(math.isfinite(value) for value in (signed, absolute)) \
                    or not _close(actual.get("signedResidual"), signed) or not _close(actual.get("absoluteResidual"), absolute):
                raise RuntimeCommitError("Runtime calibration residual does not recompute.")
            residuals.append({"fold_id": actual["foldId"], "target_period": actual["targetPeriod"],
                "actual": actual["actualTarget"], "raw_prediction": actual["rawPrediction"],
                "residual": signed, "absolute_residual": absolute})
        _, metrics = build_prequential_evaluation(residuals)
        rank, quantile = finite_sample_quantile([row["absolute_residual"] for row in residuals])
        widths = {"average": metrics["average_interval_width"], "median": metrics["median_interval_width"],
            "minimum": metrics["minimum_interval_width"], "maximum": metrics["maximum_interval_width"]}
        comparisons = {"residualCount": REQUIRED_RESIDUALS, "finalQuantileRank": rank,
            "coveredFoldCount": metrics["covered_fold_count"], "evaluatedFoldCount": metrics["evaluated_fold_count"],
            "lowerMissCount": metrics["lower_miss_count"], "upperMissCount": metrics["upper_miss_count"]}
        if any(calibration.get(key) != value for key, value in comparisons.items()) \
                or not _close(calibration.get("finalQuantileValue"), quantile) \
                or not _close(calibration.get("historicalCoverage"), metrics["observed_coverage"]) \
                or any(not _close(calibration.get("intervalWidthSummary", {}).get(key), value) for key, value in widths.items()):
            raise RuntimeCommitError("Runtime calibration summary does not recompute from its folds.")
        bounds = construct_raw_interval(float(forecast["forecastRaw"]), quantile)
        expected_uncertainty = {
            "uncertaintyStatus": "available", "lowerRaw": bounds["lower_raw"], "upperRaw": bounds["upper_raw"],
            "lowerReported": math.floor(bounds["lower_raw"]), "upperReported": math.ceil(bounds["upper_raw"]),
            "nominalCoverage": NOMINAL_COVERAGE, "historicalCoverage": metrics["observed_coverage"],
            "calibrationMethod": "prequential_expanding_window_prior_residuals_only", "residualCount": REQUIRED_RESIDUALS,
            "coveredFoldCount": metrics["covered_fold_count"], "calibrationWarmupFoldCount": WARMUP_FOLDS,
            "lowerMissCount": metrics["lower_miss_count"], "upperMissCount": metrics["upper_miss_count"],
            "uncertaintyMethod": METHOD_ID, "uncertaintyMethodVersion": METHOD_VERSION,
            "residualSourceArtifactPath": "artifacts/forecast_calibration.json", "residualSourceArtifactSha256": calibration_sha,
        }
        for key, value in expected_uncertainty.items():
            if (isinstance(value, float) and not _close(uncertainty.get(key), value)) \
                    or (not isinstance(value, float) and uncertainty.get(key) != value):
                raise RuntimeCommitError(f"Runtime uncertainty {key} does not match calibration evidence.")
        if any(not _close(uncertainty.get("intervalWidthSummary", {}).get(key), value) for key, value in widths.items()):
            raise RuntimeCommitError("Runtime uncertainty width summary mismatch.")
        if uncertainty.get("isPredictionInterval") is not False or uncertainty.get("calibratedOnSyntheticData") is not True:
            raise RuntimeCommitError("Runtime calibrated-range claim flags are invalid.")
        if forecast.get("uncertaintyAvailability") != "available" or pipeline.get("uncertaintyCalibrationPerformed") is not True:
            raise RuntimeCommitError("Runtime calibration completion flags are inconsistent.")
    elif status == "pending_dataset_specific_calibration":
        if expected_plan or calibration.get("folds") or calibration.get("residualCount") != 0:
            raise RuntimeCommitError("Pending calibration contains a complete or partial fold pool.")
        if uncertainty.get("uncertaintyStatus") != status or forecast.get("uncertaintyAvailability") != status \
                or pipeline.get("uncertaintyCalibrationPerformed") is not False:
            raise RuntimeCommitError("Pending calibration status flags are inconsistent.")
    else:
        raise RuntimeCommitError("Unknown runtime calibration status.")

    dashboard_forecast = dashboard.get("forecast", {})
    if dashboard_forecast.get("uncertaintyStatus") != uncertainty.get("uncertaintyStatus") \
            or dashboard_forecast.get("empiricalLower") != uncertainty.get("lowerReported") \
            or dashboard_forecast.get("empiricalUpper") != uncertainty.get("upperReported") \
            or dashboard_forecast.get("nominalCoverage") != uncertainty.get("nominalCoverage") \
            or dashboard_forecast.get("historicalCoverage") != uncertainty.get("historicalCoverage") \
            or dashboard_forecast.get("isPredictionInterval") is not False:
        raise RuntimeCommitError("Runtime dashboard empirical range differs from forecast uncertainty.")
    if card.get("uncertaintyStatus") != uncertainty.get("uncertaintyStatus") \
            or card.get("calibration", {}).get("status") != uncertainty.get("uncertaintyStatus"):
        raise RuntimeCommitError("Runtime model-card calibration status mismatch.")


def commit_runtime_run(runtime_root: Path, staging_path: Path, job: dict[str, Any]) -> dict[str, Any]:
    if "authoritySnapshotSha256" in job:
        from runtime_active_model import resolve_active_model
        authority=resolve_active_model(ROOT,runtime_root,job["deploymentId"])
        if authority["authoritySnapshotSha256"]!=job["authoritySnapshotSha256"] or authority["modelId"]!=job.get("resolvedModelId") or authority["modelFamily"]!=job.get("resolvedModelFamily") or authority["parameterSha256"]!=job.get("resolvedModelParameterSha256") or authority["featureOrderSha256"]!=job.get("resolvedFeatureOrderSha256") or authority["candidateRegistrySha256"]!=job.get("resolvedCandidateRegistrySha256") or authority["quickPolicySha256"]!=job.get("quickPolicySha256"):
            raise ValueError("active_model_authority_changed_before_commit")
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
    calibration = values["artifacts/forecast_calibration.json"]
    uncertainty = values["artifacts/forecast_uncertainty.json"]
    dashboard = values["artifacts/dashboard_summary.json"]
    card = values["artifacts/model_card.json"]
    identities = (job["runId"], job["jobId"], job["datasetId"], job["deploymentId"])
    for value in (run, forecast, uncertainty, card):
        if tuple(value.get(key) for key in ("runId", "jobId", "datasetId", "deploymentId")) != identities:
            raise RuntimeCommitError("Runtime artifact identity mismatch.")
    if dashboard.get("run", {}).get("runId") != job["runId"] or dashboard.get("run", {}).get("datasetId") != job["datasetId"]:
        raise RuntimeCommitError("Runtime dashboard identity mismatch.")
    if uncertainty.get("bundledP13RangeReused") is not False or uncertainty.get("rmseFallbackAllowed") is not False:
        raise RuntimeCommitError("Synthetic uncertainty reuse or RMSE fallback is prohibited.")
    if dashboard.get("preparedness") != {
        "availabilityStatus": "unavailable_missing_planning_policy", "scenarios": None,
        "counts": None, "facilities": [], "alerts": [],
    }:
        raise RuntimeCommitError("Runtime preparedness must remain unavailable and empty.")
    _validate_calibration_bundle(artifacts, forecast, calibration, uncertainty, dashboard, card, job)

    artifact_hashes = {name: sha256_file(artifacts / name) for name in sorted(REQUIRED_ARTIFACTS)}
    expected_card_hashes = card.get("artifactHashes", {})
    for name, digest in artifact_hashes.items():
        if name != "model_card.json" and expected_card_hashes.get(name) != digest:
            raise RuntimeCommitError(f"Model-card artifact hash mismatch: {name}.")
    sequence = run.get("artifactPublicationSequence", [])
    if sequence != PUBLICATION_SEQUENCE:
        raise RuntimeCommitError("The runtime artifact publication sequence is invalid.")

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
