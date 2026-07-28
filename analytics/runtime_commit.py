"""Validate and atomically commit an isolated P1.4C-2 Quick Forecast run."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from jsonschema import Draft202012Validator, FormatChecker
import pandas as pd

from empirical_range import (
    METHOD_ID, METHOD_VERSION, NOMINAL_COVERAGE, REQUIRED_RESIDUALS, WARMUP_FOLDS,
    build_prequential_evaluation, build_runtime_fold_plan, construct_raw_interval,
    finite_sample_quantile,
)
from model_factory import load_and_validate_candidate_registry
from runtime_context import require_absolute_directory, require_within
from runtime_policy import canonical_policy_sha256


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


class RunningJobUpdateError(RuntimeCommitError):
    """Raised when a shared running-job record cannot be updated safely."""


def json_sha(value: Mapping[str, Any]) -> str:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_run_record_binding(run_root: Path, commit: Mapping[str, Any]) -> None:
    """Verify the exact persisted run-record bytes bound by a 2.1 commit."""
    if commit.get("schemaVersion") != "2.1":
        if "runRecordSha256" in commit:
            raise RuntimeCommitError("Historical runtime commits cannot carry a 2.1 run-record binding.")
        return
    expected = commit.get("runRecordSha256")
    if not isinstance(expected, str) or sha256_file(run_root / "metadata" / "run.json") != expected:
        raise RuntimeCommitError("Runtime run-record hash mismatch.")


def atomic_json(path: Path, value: Any) -> None:
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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeCommitError(f"Invalid runtime JSON: {path.name}.") from exc
    if not isinstance(value, dict):
        raise RuntimeCommitError(f"Runtime JSON must be an object: {path.name}.")
    return value


def _running_job_lock_path(path: Path) -> Path:
    if path.parent.name != "running" or path.parent.parent.name != "jobs":
        raise RunningJobUpdateError("Running-job updates require a jobs/running record path.")
    return path.parent.parent / "locks" / f"{path.name}.lock"


if os.name == "nt":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class _Overlapped(ctypes.Structure):
        _fields_ = (
            ("Internal", ctypes.c_void_p),
            ("InternalHigh", ctypes.c_void_p),
            ("Offset", wintypes.DWORD),
            ("OffsetHigh", wintypes.DWORD),
            ("hEvent", wintypes.HANDLE),
        )

    _LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _lock_file_ex = _kernel32.LockFileEx
    _lock_file_ex.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_Overlapped),
    )
    _lock_file_ex.restype = wintypes.BOOL
    _unlock_file_ex = _kernel32.UnlockFileEx
    _unlock_file_ex.argtypes = (
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, ctypes.POINTER(_Overlapped),
    )
    _unlock_file_ex.restype = wintypes.BOOL


@contextmanager
def _exclusive_running_job_lock(path: Path) -> Iterator[None]:
    lock_path = _running_job_lock_path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            overlapped = _Overlapped()
            handle = wintypes.HANDLE(msvcrt.get_osfhandle(descriptor))
            if not _lock_file_ex(handle, _LOCKFILE_EXCLUSIVE_LOCK, 0, 1, 0, ctypes.byref(overlapped)):
                raise RunningJobUpdateError(
                    f"Unable to acquire running-job lock: {ctypes.WinError(ctypes.get_last_error())}"
                )
            try:
                yield
            finally:
                if not _unlock_file_ex(handle, 0, 1, 0, ctypes.byref(overlapped)):
                    raise RunningJobUpdateError(
                        f"Unable to release running-job lock: {ctypes.WinError(ctypes.get_last_error())}"
                    )
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _latest_running_job(
    path: Path,
    expected_job_id: str,
    allowed_statuses: frozenset[str],
) -> dict[str, Any]:
    if not path.is_file():
        raise RunningJobUpdateError("The running-job record no longer exists.")
    latest = _load_json(path)
    if latest.get("jobId") != expected_job_id or path.name != f"{expected_job_id}.json":
        raise RunningJobUpdateError("Running-job identity mismatch.")
    if latest.get("status") not in allowed_statuses:
        raise RunningJobUpdateError("The running-job record is not patchable in its current state.")
    return latest


def patch_running_job(
    path: Path,
    patch: Mapping[str, Any],
    *,
    expected_job_id: str,
    allowed_statuses: frozenset[str] = frozenset({"queued", "running"}),
) -> dict[str, Any]:
    if not isinstance(patch, Mapping) or any(key in patch for key in ("jobId", "schemaVersion", "jobKind")):
        raise RunningJobUpdateError("Running-job patches cannot replace identity fields.")
    with _exclusive_running_job_lock(path):
        latest = _latest_running_job(path, expected_job_id, allowed_statuses)
        latest.update(dict(patch))
        atomic_json(path, latest)
        return latest


def finalize_running_job(
    path: Path,
    destination: Path,
    patch: Mapping[str, Any],
    *,
    expected_job_id: str,
) -> dict[str, Any]:
    if destination.name != path.name or destination.parent.name not in {"completed", "failed"}:
        raise RunningJobUpdateError("Running-job finalization destination is invalid.")
    if not isinstance(patch, Mapping) or patch.get("status") not in {"completed", "failed", "timed_out"}:
        raise RunningJobUpdateError("Running-job finalization requires an explicit terminal status.")
    with _exclusive_running_job_lock(path):
        latest = _latest_running_job(path, expected_job_id, frozenset({"running"}))
        if destination.exists():
            raise RunningJobUpdateError("A finalized job record already exists.")
        latest.update(dict(patch))
        atomic_json(path, latest)
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, destination)
        return latest


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
    job: dict[str, Any], run: dict[str, Any],
) -> None:
    pipeline = _load_json(artifacts / "pipeline_run_summary.json")
    calibration_sha = sha256_file(artifacts / "forecast_calibration.json")
    is_p2 = run.get("schemaVersion") in {"2.0", "2.1"}
    if tuple(calibration.get(key) for key in ("runId", "jobId", "datasetId")) != (
        job["runId"], job["jobId"], job["datasetId"],
    ):
        raise RuntimeCommitError("Runtime calibration identity mismatch.")
    expected_policy = (run.get("deploymentId"), run.get("policyId"), run.get("policyVersion"), run.get("policySha256"))
    if (calibration.get("deploymentProfileId"), calibration.get("policyId"), calibration.get("policyVersion"), calibration.get("policySha256")) != (
        expected_policy
    ):
        raise RuntimeCommitError("Runtime calibration policy identity mismatch.")
    policy_object = {"id": run.get("policyId"), "version": run.get("policyVersion"), "sha256": run.get("policySha256")}
    if forecast.get("policy") != policy_object or card.get("policy") != policy_object \
            or dashboard.get("evidence", {}).get("policy") != policy_object:
        raise RuntimeCommitError("Runtime policy evidence does not reconcile across artifacts.")
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
    status = calibration.get("calibrationStatus")
    available_status = "governed_available" if is_p2 else "available"
    unavailable_status = "unavailable" if is_p2 else "pending_dataset_specific_calibration"
    if status == available_status and calibration.get("foldPlanSha256") != expected_plan_sha:
        raise RuntimeCommitError("Runtime calibration fold-plan hash mismatch.")
    if status == available_status:
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
            "uncertaintyStatus": available_status, "lowerRaw": bounds["lower_raw"], "upperRaw": bounds["upper_raw"],
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
        if forecast.get("uncertaintyAvailability") != available_status or pipeline.get("uncertaintyCalibrationPerformed") is not True:
            raise RuntimeCommitError("Runtime calibration completion flags are inconsistent.")
        if is_p2 and (calibration.get("modelId") != "random_forest" or calibration.get("modelFamily") != "RandomForestRegressor"
                or uncertainty.get("forecastPresentationMode") != "point_and_interval"
                or uncertainty.get("calibrationStatus") != "governed_available"
                or uncertainty.get("uncertaintyReasonCode") is not None):
            raise RuntimeCommitError("Governed p2 calibration presentation or model identity is invalid.")
    elif status == unavailable_status:
        if calibration.get("folds") or calibration.get("residualCount") != 0:
            raise RuntimeCommitError("Unavailable calibration contains residual evidence.")
        if not is_p2 and expected_plan:
            raise RuntimeCommitError("Pending calibration contains a complete or partial fold pool.")
        summary_fields = ("finalQuantileRank", "finalQuantileValue", "historicalCoverage", "coveredFoldCount",
                          "evaluatedFoldCount", "lowerMissCount", "upperMissCount", "intervalWidthSummary")
        if any(calibration.get(key) is not None for key in summary_fields):
            raise RuntimeCommitError("Unavailable calibration contains non-null summaries.")
        if uncertainty.get("uncertaintyStatus") != status or forecast.get("uncertaintyAvailability") != status \
                or pipeline.get("uncertaintyCalibrationPerformed") is not False:
            raise RuntimeCommitError("Unavailable calibration status flags are inconsistent.")
        if is_p2:
            null_uncertainty = ("lowerRaw", "upperRaw", "lowerReported", "upperReported", "nominalCoverage",
                                "historicalCoverage", "calibrationMethod", "coveredFoldCount", "calibrationWarmupFoldCount",
                                "lowerMissCount", "upperMissCount", "intervalWidthSummary", "uncertaintyMethod",
                                "uncertaintyMethodVersion", "residualSourceArtifactPath", "residualSourceArtifactSha256")
            if any(uncertainty.get(key) is not None for key in null_uncertainty) or uncertainty.get("residualCount") != 0:
                raise RuntimeCommitError("Unavailable p2 calibration emitted residual evidence or interval bounds.")
            if (uncertainty.get("forecastPresentationMode"), uncertainty.get("calibrationStatus"), uncertainty.get("uncertaintyReasonCode")) != (
                "point_only", "unavailable", "model_calibration_unavailable"
            ):
                raise RuntimeCommitError("Unavailable p2 calibration presentation is invalid.")
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
    if is_p2:
        p2_status = uncertainty.get("calibrationStatus")
        presentation = uncertainty.get("forecastPresentationMode")
        reason = uncertainty.get("uncertaintyReasonCode")
        for artifact_status, artifact_presentation, artifact_reason in (
            (forecast.get("calibrationStatus"), forecast.get("forecastPresentationMode"), forecast.get("uncertaintyReasonCode")),
            (dashboard_forecast.get("calibrationStatus"), dashboard_forecast.get("forecastPresentationMode"), dashboard_forecast.get("uncertaintyReasonCode")),
            (card.get("calibrationStatus"), card.get("forecastPresentationMode"), card.get("uncertaintyReasonCode")),
        ):
            if (artifact_status, artifact_presentation, artifact_reason) != (p2_status, presentation, reason):
                raise RuntimeCommitError("P2 calibration presentation differs across artifacts.")


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
    calibration = values["artifacts/forecast_calibration.json"]
    uncertainty = values["artifacts/forecast_uncertainty.json"]
    dashboard = values["artifacts/dashboard_summary.json"]
    card = values["artifacts/model_card.json"]
    contract_version = run.get("schemaVersion")
    artifact_versions = {
        run.get("schemaVersion"), forecast.get("schemaVersion"), calibration.get("schemaVersion"),
        uncertainty.get("schemaVersion"), dashboard.get("schemaVersion"), card.get("schemaVersion"),
    }
    if artifact_versions != {contract_version} or contract_version not in {"1.0", "2.0", "2.1"}:
        raise RuntimeCommitError("Mixed p1/p2 runtime artifact contracts are prohibited.")

    if contract_version in {"2.0", "2.1"}:
        from runtime_active_model import resolve_active_model_p2_v2
        authority = resolve_active_model_p2_v2(
            repository_root=ROOT, runtime_root=runtime_root, deployment_id=job["deploymentId"]
        )
        quick_policy_version = job.get("policyVersion")
        registry_name = "candidate_models.json" if quick_policy_version == "p2-v2" else "candidate_models_p2-v1.json"
        registry, registry_sha = load_and_validate_candidate_registry(ROOT / "config" / registry_name)
        candidate = next((item for item in registry["candidates"] if item["model_id"] == authority["modelId"]), None)
        if candidate is None:
            raise RuntimeCommitError("P2 active model is absent from the candidate registry.")
        expected_authority = {
            "assignmentId": authority["assignmentId"], "assignmentCommitSha256": authority["assignmentCommitSha256"],
            "activeModelId": authority["modelId"], "modelFamily": authority["modelFamily"],
            "parameterSha256": authority["parameterSha256"], "preprocessingIdentity": authority["preprocessingIdentity"],
            "candidateRegistrySha256": authority["candidateRegistrySha256"], "featureOrderSha256": authority["featureOrderSha256"],
            "lifecyclePolicyId": authority["lifecyclePolicyId"], "lifecyclePolicyVersion": authority["lifecyclePolicyVersion"],
            "lifecyclePolicySha256": authority["lifecyclePolicySha256"],
        }
        if contract_version == "2.1":
            expected_authority.update({
                "assignmentAction": authority["assignmentAction"],
                "authoritySnapshotSha256": authority["authoritySnapshotSha256"],
            })
            if (
                job.get("assignmentAction"),
                job.get("authoritySnapshotSha256"),
            ) != (
                authority["assignmentAction"],
                authority["authoritySnapshotSha256"],
            ):
                raise RuntimeCommitError("active_model_authority_changed_before_commit")
        if any(run.get(key) != value for key, value in expected_authority.items()):
            raise RuntimeCommitError("active_model_authority_changed_before_commit")
        if registry_sha != authority["candidateRegistrySha256"] or (
            candidate.get("model_family"), candidate.get("parameters_sha256"), candidate.get("preprocessing_identity"), candidate.get("feature_order_sha256")
        ) != (
            authority["modelFamily"], authority["parameterSha256"], authority["preprocessingIdentity"], authority["featureOrderSha256"]
        ):
            raise RuntimeCommitError("P2 assignment identity does not reconcile with the candidate registry.")

        quick_policy_name = "quick_forecast_policy.json" if quick_policy_version == "p2-v2" else "quick_forecast_policy_p2-v1.json"
        quick_policy = _load_json(ROOT / "config/deployments" / job["deploymentId"] / quick_policy_name)
        quick_policy_sha = canonical_policy_sha256(quick_policy)
        if (run.get("policyId"), run.get("policyVersion"), run.get("policySha256")) != (
            quick_policy.get("policyId"), quick_policy.get("policyVersion"), quick_policy_sha
        ):
            raise RuntimeCommitError("P2 Quick Forecast policy identity mismatch.")

        artifact_authorities = (
            {"assignmentId": forecast.get("assignmentId"), "assignmentCommitSha256": forecast.get("assignmentCommitSha256"),
             "activeModelId": forecast.get("activeModelId"), "modelFamily": forecast.get("modelFamily"),
             "parameterSha256": forecast.get("parameterHash"), "preprocessingIdentity": forecast.get("preprocessingIdentity"),
             "candidateRegistrySha256": forecast.get("candidateRegistrySha256"), "featureOrderSha256": forecast.get("trainingDataIdentity", {}).get("featureOrderSha256"),
             "lifecyclePolicyId": forecast.get("lifecyclePolicyId"), "lifecyclePolicyVersion": forecast.get("lifecyclePolicyVersion"), "lifecyclePolicySha256": forecast.get("lifecyclePolicySha256")},
            {"assignmentId": calibration.get("assignmentId"), "assignmentCommitSha256": calibration.get("assignmentCommitSha256"),
             "activeModelId": calibration.get("modelId"), "modelFamily": calibration.get("modelFamily"),
             "parameterSha256": calibration.get("modelParametersSha256"), "preprocessingIdentity": calibration.get("preprocessingIdentity"),
             "candidateRegistrySha256": calibration.get("candidateRegistrySha256"), "featureOrderSha256": calibration.get("featureOrderSha256")},
            {"assignmentId": uncertainty.get("assignmentId"), "assignmentCommitSha256": uncertainty.get("assignmentCommitSha256"),
             "activeModelId": uncertainty.get("activeModelId"), "modelFamily": uncertainty.get("modelFamily"),
             "parameterSha256": uncertainty.get("parameterHash"), "preprocessingIdentity": uncertainty.get("preprocessingIdentity"),
             "candidateRegistrySha256": uncertainty.get("candidateRegistrySha256"), "featureOrderSha256": uncertainty.get("featureOrderSha256")},
            {"assignmentId": card.get("assignmentId"), "assignmentCommitSha256": card.get("assignmentCommitSha256"),
             "activeModelId": card.get("model", {}).get("id"), "modelFamily": card.get("model", {}).get("family"),
             "parameterSha256": card.get("model", {}).get("parameterHash"), "preprocessingIdentity": card.get("model", {}).get("preprocessingIdentity"),
             "candidateRegistrySha256": card.get("model", {}).get("candidateRegistrySha256"), "featureOrderSha256": card.get("features", {}).get("orderSha256")},
        )
        if contract_version == "2.1":
            artifact_authorities = (
                {**artifact_authorities[0],
                 "assignmentAction": forecast.get("assignmentAction"),
                 "authoritySnapshotSha256": forecast.get("authoritySnapshotSha256")},
                artifact_authorities[1],
                artifact_authorities[2],
                {**artifact_authorities[3],
                 "assignmentAction": card.get("assignmentAction"),
                 "authoritySnapshotSha256": card.get("authoritySnapshotSha256")},
            )
        for artifact_authority in artifact_authorities:
            if any(artifact_authority.get(key) != expected_authority[key] for key in artifact_authority):
                raise RuntimeCommitError("P2 artifact authority identity mismatch.")
        lifecycle_policy = {"id": authority["lifecyclePolicyId"], "version": authority["lifecyclePolicyVersion"], "sha256": authority["lifecyclePolicySha256"]}
        if card.get("lifecyclePolicy") != lifecycle_policy or dashboard.get("evidence", {}).get("lifecyclePolicy") != lifecycle_policy:
            raise RuntimeCommitError("P2 lifecycle policy provenance mismatch.")
        if forecast.get("deploymentModelAdopted") is not False or card.get("deploymentModelAdopted") is not False:
            raise RuntimeCommitError("One-run Quick Forecast cannot adopt a deployment model.")
    elif "authoritySnapshotSha256" in job:
        from runtime_active_model import resolve_historical_active_model_p2_v1
        authority = resolve_historical_active_model_p2_v1(
            repository_root=ROOT, runtime_root=runtime_root, deployment_id=job["deploymentId"]
        )
        if authority["authoritySnapshotSha256"] != job["authoritySnapshotSha256"] or authority["modelId"] != job.get("resolvedModelId") or authority["modelFamily"] != job.get("resolvedModelFamily") or authority["parameterSha256"] != job.get("resolvedModelParameterSha256") or authority["featureOrderSha256"] != job.get("resolvedFeatureOrderSha256") or authority["candidateRegistrySha256"] != job.get("resolvedCandidateRegistrySha256") or authority["quickPolicySha256"] != job.get("quickPolicySha256"):
            raise RuntimeCommitError("active_model_authority_changed_before_commit")
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
    _validate_calibration_bundle(artifacts, forecast, calibration, uncertainty, dashboard, card, job, run)

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
        "schemaVersion": "2.1" if contract_version == "2.1" else "1.0",
        "runId": job["runId"], "jobId": job["jobId"],
        "workspaceId": job["workspaceId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast",
        "sourceType": "uploaded", "status": "committed", "policySha256": run["policySha256"],
        "artifactHashes": artifact_hashes, "modelCardPublishedLast": True,
        "prohibitedArtifactsAbsent": True, "committedAt": committed_at,
    }
    if contract_version == "2.1":
        commit["runRecordSha256"] = sha256_file(metadata / "run.json")
    verify_run_record_binding(staging_root, commit)
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
        verify_run_record_binding(committed_root, commit)
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
