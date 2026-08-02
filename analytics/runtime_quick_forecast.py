"""Execute one policy-approved uploaded Quick Forecast in isolated staging."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from feature_engineering import FEATURE_COLUMNS, build_features, build_inference_features
from empirical_range import (
    HORIZON_WEEKS as CALIBRATION_HORIZON_WEEKS,
    INITIAL_TRAINING_ROWS,
    EMBARGO_ROWS,
    FOLD_STEP_ROWS,
    METHOD_ID,
    METHOD_VERSION,
    NOMINAL_COVERAGE,
    REQUIRED_RESIDUALS,
    WARMUP_FOLDS,
    advance_iso_period,
    build_prequential_evaluation,
    construct_raw_interval,
    finite_sample_quantile,
    generate_runtime_rf_residuals,
)
from model_factory import build_candidate_estimator, load_and_validate_candidate_registry, load_historical_candidate_registry
from prediction_interval import (
    PredictionIntervalError,
    calibration_metrics as assessment_calibration_metrics,
    construct_count_interval,
    resolve_assignment_calibration,
)
from runtime_commit import atomic_json, commit_runtime_run, patch_running_job, sha256_file
from runtime_active_model import resolve_active_model_p2_v2, resolve_historical_active_model_p2_v1
from runtime_assessment_policy import PREVIOUS_CANDIDATE_REGISTRY_PATH
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_policy import canonical_policy_sha256, evaluate_quick_forecast_policy, load_and_validate_quick_forecast_policy
from runtime_validate import CONTRACT_VERSION, HORIZON_WEEKS, TARGET, compute_dataset_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _period(year: int, week: int) -> str:
    return f"{year}-W{week:02d}"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return value


def _single(frame: pd.DataFrame, column: str) -> str | None:
    values = {str(value).strip() for value in frame[column].tolist()} if column in frame else set()
    values.discard("")
    return next(iter(values)) if len(values) == 1 else None


def _approximated(frame: pd.DataFrame) -> bool | None:
    if "is_approximated" not in frame:
        return None
    values = {str(value).strip().lower() for value in frame["is_approximated"].tolist()}
    return "true" in values if values.issubset({"true", "false"}) else None


def _update_job(path: Path, job: dict[str, Any], **changes: Any) -> None:
    job.update(changes)
    job["updatedAt"] = _now()
    patch_running_job(
        path,
        {**changes, "updatedAt": job["updatedAt"]},
        expected_job_id=str(job["jobId"]),
    )


def _write_json_artifact(path: Path, value: Any) -> None:
    atomic_json(path, value)


def _load_quick_forecast_policy(deployment_id: str, policy_version: str | None) -> tuple[dict[str, Any], str, bool]:
    p2_filename = {
        "p2-v1": "quick_forecast_policy_p2-v1.json",
        "p2-v2": "quick_forecast_policy.json",
    }.get(policy_version)
    if p2_filename is not None:
        p2_policy_path = ROOT / "config" / "deployments" / deployment_id / p2_filename
        p2_policy = json.loads(p2_policy_path.read_text(encoding="utf-8"))
        if p2_policy.get("schemaVersion") == "2.0" and p2_policy.get("policyVersion") == policy_version:
            return p2_policy, canonical_policy_sha256(p2_policy), True
        raise ValueError("Quick Forecast policy archive identity mismatch.")
    policy, policy_hash = load_and_validate_quick_forecast_policy(deployment_id)
    return policy, policy_hash, False


def execute(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = require_absolute_directory(args.runtime_root, "runtime root")
    job_path = require_within(runtime_root, args.job_record, "job record")
    workspace = require_within(runtime_root, args.workspace, "workspace")
    staging = require_within(runtime_root, args.staging, "staging run")
    if workspace.parent != (runtime_root / "workspaces").resolve() or staging.parent != (runtime_root / "staging").resolve():
        raise ValueError("Runtime execution paths have invalid parents.")
    job = _json(job_path)
    if job.get("status") != "running" or job.get("workflowMode") != "quick_forecast":
        raise ValueError("The claimed job is not runnable.")
    if staging.name != job["runId"] or workspace.name != job["workspaceId"]:
        raise ValueError("Job paths do not match job identities.")

    policy, policy_hash, is_p2 = _load_quick_forecast_policy(job["deploymentId"], job.get("policyVersion"))
    policy_id = policy.get("policyId") if is_p2 else policy.get("policy_id")
    policy_version = policy.get("policyVersion") if is_p2 else policy.get("policy_version")
    contract_version = job.get("schemaVersion")
    if (is_p2 and contract_version not in {"2.0", "2.1"}) or (not is_p2 and contract_version != "1.0"):
        raise ValueError("Quick Forecast job contract is incompatible with the governed policy.")
    is_p21 = is_p2 and contract_version == "2.1"
    is_pi = is_p21
    artifact_schema_version = contract_version if is_p2 else "1.0"
    if (
        job.get("policyId"),
        job.get("policyVersion"),
        job.get("policySha256"),
        job.get("quickPolicyId"),
        job.get("quickPolicyVersion"),
        job.get("quickPolicySha256"),
    ) != (
        policy_id,
        policy_version,
        policy_hash,
        policy_id if "quickPolicyId" in job else None,
        policy_version if "quickPolicyVersion" in job else None,
        policy_hash if "quickPolicySha256" in job else None,
    ):
        raise ValueError("Quick Forecast policy identity changed after queueing.")

    active_authority = None
    if "authoritySnapshotSha256" in job:
        try:
            if is_p2:
                authority = resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime_root, deployment_id=job["deploymentId"])
            else:
                authority = resolve_historical_active_model_p2_v1(
                    repository_root=ROOT, runtime_root=runtime_root, deployment_id=job["deploymentId"]
                )
        except Exception as exc:
            raise ValueError(f"active_model_not_assigned: {exc}") from exc
        active_authority = authority
        expected_authority = {
            "authoritySnapshotSha256": job.get("authoritySnapshotSha256"),
            "modelId": job.get("resolvedModelId"),
            "modelFamily": job.get("resolvedModelFamily"),
            "parameterSha256": job.get("resolvedModelParameterSha256"),
            "candidateRegistrySha256": job.get("resolvedCandidateRegistrySha256"),
            "featureOrderSha256": job.get("resolvedFeatureOrderSha256"),
        }
        if is_p2:
            expected_authority.update({
                "preprocessingIdentity": job.get("resolvedPreprocessingIdentity"),
                "assignmentId": job.get("assignmentId"),
                "assignmentCommitSha256": job.get("assignmentCommitSha256"),
                "assignmentAction": job.get("assignmentAction"),
                "lifecyclePolicyId": job.get("lifecyclePolicyId"),
                "lifecyclePolicyVersion": job.get("lifecyclePolicyVersion"),
                "lifecyclePolicySha256": job.get("lifecyclePolicySha256"),
            })
        if any(authority.get(key) != value for key, value in expected_authority.items()):
            raise ValueError("stale_or_incompatible_active_model_authority")

    workspace_metadata_path = workspace / "metadata" / "workspace.json"
    validation_path = workspace / "metadata" / "validation.json"
    workspace_metadata = _json(workspace_metadata_path)
    validation_bytes = validation_path.read_bytes()
    validation = json.loads(validation_bytes.decode("utf-8"))
    if hashlib.sha256(validation_bytes).hexdigest() != job["validationRecordSha256"]:
        raise ValueError("The authoritative validation record changed after queueing.")
    if workspace_metadata.get("status") != "ready" or workspace_metadata.get("datasetId") != job["datasetId"]:
        raise ValueError("The workspace is no longer ready for this job.")
    canonical_case = workspace / "inputs" / "canonical" / "dengue_cases.csv"
    canonical_climate = workspace / "inputs" / "canonical" / "climate_data.csv"
    if sha256_file(canonical_case) != validation["files"]["canonical"]["dengueSha256"] or sha256_file(canonical_climate) != validation["files"]["canonical"]["climateSha256"]:
        raise ValueError("Canonical uploaded files changed after validation.")
    feature_hash = validation["datasetIdentity"]["featureOrderSha256"]
    if compute_dataset_id(canonical_case.read_bytes(), canonical_climate.read_bytes(), job["deploymentId"], feature_hash) != job["datasetId"]:
        raise ValueError("Dataset identity could not be recomputed.")

    assigned_model_id = None
    assigned_model_family = None
    assigned_param_sha = None
    assigned_assignment_id = None
    assigned_commit_sha = None
    assigned_action = None
    authority_snapshot_sha = None
    assigned_preprocessing_identity = None
    lifecycle_policy_id = None
    lifecycle_policy_version = None
    lifecycle_policy_sha = None

    if is_p2:
        try:
            active_authority = active_authority or resolve_active_model_p2_v2(
                repository_root=ROOT, runtime_root=runtime_root, deployment_id=job["deploymentId"]
            )
        except Exception as exc:
            raise ValueError(f"active_model_not_assigned: {exc}") from exc

        if active_authority.get("authoritySource") != "committed_assignment":
            raise ValueError("active_model_not_assigned")

        assigned_model_id = active_authority["modelId"]
        assigned_model_family = active_authority["modelFamily"]
        assigned_param_sha = active_authority["parameterSha256"]
        assigned_assignment_id = active_authority["assignmentId"]
        assigned_commit_sha = active_authority["assignmentCommitSha256"]
        assigned_action = active_authority["assignmentAction"]
        authority_snapshot_sha = active_authority["authoritySnapshotSha256"]
        assigned_preprocessing_identity = active_authority["preprocessingIdentity"]
        candidate_registry_sha = active_authority["candidateRegistrySha256"]
        authority_feature_hash = active_authority["featureOrderSha256"]
        lifecycle_policy_id = active_authority["lifecyclePolicyId"]
        lifecycle_policy_version = active_authority["lifecyclePolicyVersion"]
        lifecycle_policy_sha = active_authority["lifecyclePolicySha256"]

        registry, registry_hash = (
            load_and_validate_candidate_registry()
            if policy_version == "p2-v2"
            else load_and_validate_candidate_registry(PREVIOUS_CANDIDATE_REGISTRY_PATH)
        )
        if registry_hash != candidate_registry_sha:
            raise ValueError("Candidate registry hash mismatch against active authority.")
        if feature_hash != authority_feature_hash:
            raise ValueError("Feature order hash mismatch against active authority.")

        candidate = next((c for c in registry["candidates"] if c["model_id"] == assigned_model_id), None)
        if candidate is None:
            raise ValueError(f"Unknown candidate model: {assigned_model_id}")
        if candidate.get("candidate_class") != "learned_model" or candidate.get("selection_role") != "learned_selectable" or candidate.get("selectable") is not True:
            raise ValueError(f"Assigned model {assigned_model_id} is not a selectable learned candidate.")
        if candidate.get("model_family") != assigned_model_family:
            raise ValueError("Model family mismatch against candidate registry.")
        if candidate.get("parameters_sha256") != assigned_param_sha:
            raise ValueError("Parameter SHA mismatch against candidate registry.")
        if candidate.get("preprocessing_identity") != assigned_preprocessing_identity:
            raise ValueError("Preprocessing identity mismatch against candidate registry.")
        if candidate.get("feature_order_sha256") != feature_hash:
            raise ValueError("Feature order SHA mismatch against candidate registry.")
    else:
        profile = _json(ROOT / "config" / "deployments" / job["deploymentId"] / "profile.json")
        assigned_model_id = "random_forest"
        assigned_model_family = "RandomForestRegressor"
        registry, registry_hash = load_historical_candidate_registry()
        candidate = next((c for c in registry["candidates"] if c["model_id"] == assigned_model_id), None)
        assigned_param_sha = candidate["parameters_sha256"]

    _update_job(job_path, job, progress="building_features")
    cases = pd.read_csv(canonical_case)
    climate = pd.read_csv(canonical_climate)
    training, _ = build_features(canonical_case, canonical_climate, output_path=None)
    inference = build_inference_features(canonical_case, canonical_climate)
    if list(training.loc[:, FEATURE_COLUMNS].columns) != list(FEATURE_COLUMNS) or len(FEATURE_COLUMNS) != 18 or inference.empty:
        raise ValueError("The governed 18-feature contract is unavailable.")
    latest = inference.iloc[-1]

    if not is_p2:
        profile = _json(ROOT / "config" / "deployments" / job["deploymentId"] / "profile.json")
        quick = evaluate_quick_forecast_policy(policy, {
            "validation_passed": validation.get("status") == "ready",
            "deployment_id": job["deploymentId"], "deployment_gate": profile.get("deployment_gate"),
            "case_geography": validation["datasetIdentity"].get("geography"),
            "climate_geography": validation["datasetIdentity"].get("geography"),
            "canonical_contract_version": validation["normalization"]["canonicalContractVersion"],
            "feature_order_sha256": feature_hash, "constructible_feature_count": len(FEATURE_COLUMNS),
            "target": TARGET, "horizon_weeks": HORIZON_WEEKS,
            "approved_model_id": profile["model"]["model_id"], "approved_model_family": profile["model"]["model_family"],
            "approved_model_parameters_sha256": profile["model"]["model_parameters_sha256"],
            "candidate_registry_sha256": policy.get("candidate_registry_sha256") or policy.get("candidateRegistrySha256"),
            "source_metadata": {
                "cases": {"source_type": _single(cases, "source_type"), "aggregation_method": "weekly_epi_week_case_count", "contains_approximated_values": _approximated(cases)},
                "climate": {"source_type": _single(climate, "source_type"), "aggregation_method": _single(climate, "aggregation_method"), "contains_approximated_values": _approximated(climate)},
            },
            "overlap_weeks": validation["counts"]["overlapWeeks"], "labelled_rows": len(training),
            "chronological_order_valid": True, "duplicate_periods_absent": True, "contiguous_history": True,
            "case_climate_aligned": True, "valid_inference_row": bool(pd.to_numeric(latest.loc[FEATURE_COLUMNS], errors="coerce").notna().all()),
        })
        if not quick["eligible"] or quick["approvedModelId"] != "random_forest":
            raise ValueError("The workspace no longer passes Quick Forecast policy evaluation.")

    if staging.exists() and {item.name for item in staging.iterdir()} - {"logs"}:
        raise ValueError("The staging run already contains untrusted content.")
    for relative in ("metadata", "inputs/original", "inputs/canonical", "artifacts", "logs"):
        (staging / relative).mkdir(parents=True, exist_ok=False if relative == "metadata" else True)
    shutil.copy2(workspace / "inputs" / "original" / "dengue.csv", staging / "inputs" / "original" / "dengue.csv")
    shutil.copy2(workspace / "inputs" / "original" / "climate.csv", staging / "inputs" / "original" / "climate.csv")
    shutil.copy2(canonical_case, staging / "inputs" / "canonical" / "dengue_cases.csv")
    shutil.copy2(canonical_climate, staging / "inputs" / "canonical" / "climate_data.csv")
    shutil.copy2(validation_path, staging / "metadata" / "validation.json")

    generated_at = _now()
    X = training.loc[:, FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise")
    y = pd.to_numeric(training[TARGET], errors="raise")
    if not np.isfinite(X.to_numpy()).all() or not np.isfinite(y.to_numpy()).all() or (y < 0).any():
        raise ValueError("Training data contains invalid values.")
    inference_row = latest.loc[FEATURE_COLUMNS].to_frame().T.astype(float)

    estimator = build_candidate_estimator(assigned_model_id, registry)
    _update_job(job_path, job, progress="training_approved_model")
    estimator.fit(X, y)
    _update_job(job_path, job, progress="generating_point_forecast")
    raw = float(estimator.predict(inference_row)[0])
    if not math.isfinite(raw) or raw < 0:
        raise ValueError(f"{assigned_model_id} returned an invalid point forecast.")

    published = max(0.0, raw)
    reported = int(round(published))
    latest_cases = int(latest["cases"])
    direction = "Increasing" if reported > latest_cases else "Decreasing" if reported < latest_cases else "Stable"
    target_year, target_week = advance_iso_period(int(latest["epi_year"]), int(latest["epi_week"]), HORIZON_WEEKS)
    target_period = _period(target_year, target_week)
    feature_bytes = training.to_csv(index=False, lineterminator="\n").encode("utf-8")
    feature_matrix_hash = hashlib.sha256(feature_bytes).hexdigest()
    training_identity = {
        "datasetId": job["datasetId"], "featureMatrixSha256": feature_matrix_hash,
        "trainingRowCount": len(training), "trainingPeriod": {
            "start": _period(int(training.iloc[0]["epi_year"]), int(training.iloc[0]["epi_week"])),
            "end": _period(int(training.iloc[-1]["epi_year"]), int(training.iloc[-1]["epi_week"])),
        }, "featureOrderSha256": feature_hash,
    }

    artifacts = staging / "artifacts"
    input_manifest = {
        "schemaVersion": "1.0", "runId": job["runId"], "datasetId": job["datasetId"],
        "validationRecordSha256": job["validationRecordSha256"],
        "originalHashes": validation["files"]["original"], "canonicalHashes": validation["files"]["canonical"],
        "featureOrderSha256": feature_hash, "generatedAt": generated_at,
    }
    _write_json_artifact(artifacts / "input_manifest.json", input_manifest)
    (artifacts / "model_features.csv").write_bytes(feature_bytes)
    policy_identity = {"id": policy.get("policy_id") or policy.get("policyId"), "version": policy.get("policy_version") or policy.get("policyVersion"), "sha256": policy_hash}

    # Calibration evaluation. Current p2 forecasts consume only the assigned candidate's
    # immutable B9.L assessment OOF residuals; the legacy p1 path remains readable.
    available_fold_count = max(0, len(training) - INITIAL_TRAINING_ROWS - EMBARGO_ROWS)
    supports_calibration = (assigned_model_id == "random_forest") if not is_pi else True
    calibration_result: dict[str, Any] | None = None
    calibration_metrics = None
    final_quantile_rank = None
    final_quantile_value = None
    calibration_available = False

    if is_pi:
        if active_authority is None:
            raise ValueError("Current assignment authority is unavailable for calibration.")
        try:
            calibration_result = resolve_assignment_calibration(runtime_root, active_authority, assigned_model_id)
        except PredictionIntervalError as exc:
            if str(exc) == "calibration_not_available_for_assignment":
                calibration_result = {"status": "point_only", "reason": str(exc), "residuals": []}
            else:
                raise ValueError(f"assessment_calibration_integrity_failed: {exc}") from exc
        calibration_available = calibration_result["status"] == "available"
        if calibration_available:
            final_quantile_rank = int(calibration_result["quantileRank"])
            final_quantile_value = float(calibration_result["absoluteResidualQuantile"])
            calibration_metrics = assessment_calibration_metrics(calibration_result["residuals"], final_quantile_value)
    elif supports_calibration:
        calibration_result = generate_runtime_rf_residuals(
            training,
            registry,
            registry_sha256=registry_hash,
            expected_registry_sha256=registry_hash,
            expected_parameters_sha256=candidate["parameters_sha256"],
        )
        calibration_available = calibration_result["status"] == "available"
        if calibration_available:
            _, calibration_metrics = build_prequential_evaluation(
                calibration_result["residuals"], nominal_coverage=NOMINAL_COVERAGE
            )
            final_quantile_rank, final_quantile_value = finite_sample_quantile(
                [row["absolute_residual"] for row in calibration_result["residuals"]],
                nominal_coverage=NOMINAL_COVERAGE,
            )

    if calibration_result is None:
        calibration_result = {"status": "unavailable", "folds": [], "foldPlanSha256": "0" * 64}

    calibration_reason = None if calibration_available else (
        calibration_result.get("reason", "model_calibration_unavailable") if is_pi else "insufficient_residual_folds"
    )
    calibration_limitations = ([
        f"The empirical prediction interval uses only leakage-safe rolling-origin OOF residuals for {assigned_model_family} from its exact source assessment.",
        "The calibration folds also informed model selection; this is not an untouched post-selection or prospective coverage guarantee.",
        "The source snapshot is retrospective latest-revision evidence; historical data vintages are unavailable.",
        "Preparedness scenarios, bundled bounds, in-sample residuals, and RMSE sensitivity are not calibration inputs.",
    ] if calibration_available and is_pi else ([
        f"The empirical range uses dataset-specific out-of-sample {assigned_model_family} rolling-origin residuals.",
        "Targets overlap and residuals are temporally dependent; historical coverage does not guarantee future coverage.",
        "The range is not a probability statement or prediction interval.",
        "The currently governed uploaded source scope is deterministic synthetic benchmark data.",
        "Preparedness scenarios, bundled bounds, and RMSE sensitivity are not calibration inputs.",
    ] if calibration_available else [
        "The assigned model's source assessment does not contain sufficient governed B9.PI calibration evidence." if is_pi else f"Dataset-specific calibration requires exactly 68 complete residual folds; this dataset provides {available_fold_count}.",
        "The point forecast remains valid; no in-sample, pooled-candidate, benchmark, preparedness, or percentage fallback was used.",
    ]))
    width_summary = None if calibration_metrics is None else (
        calibration_metrics["intervalWidthSummary"] if is_pi else {
            "average": calibration_metrics["average_interval_width"],
            "median": calibration_metrics["median_interval_width"],
            "minimum": calibration_metrics["minimum_interval_width"],
            "maximum": calibration_metrics["maximum_interval_width"],
        }
    )
    source_residuals = calibration_result.get("residuals", []) if is_pi else calibration_result.get("folds", [])
    calibration_policy = calibration_result.get("policy", {}) if is_pi else {}
    nominal_coverage = float(calibration_result.get("nominalLevel", NOMINAL_COVERAGE)) if is_pi else NOMINAL_COVERAGE
    calibration_artifact = {
        "schemaVersion": artifact_schema_version, "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentProfileId": job["deploymentId"], "policyId": policy_identity["id"], "policyVersion": policy_identity["version"],
        "policySha256": policy_hash, "modelId": assigned_model_id, "modelFamily": assigned_model_family,
        "modelParametersSha256": candidate["parameters_sha256"], "candidateRegistrySha256": registry_hash,
        "featureOrder": list(FEATURE_COLUMNS), "featureOrderSha256": feature_hash, "targetColumn": TARGET,
        "forecastHorizonWeeks": CALIBRATION_HORIZON_WEEKS, "initialTrainingRows": INITIAL_TRAINING_ROWS,
        "embargoRows": 2 if is_pi else EMBARGO_ROWS, "foldStepRows": FOLD_STEP_ROWS,
        "requiredResidualCount": int(calibration_result.get("minimumRequired", 9)) if is_pi else REQUIRED_RESIDUALS,
        "calibrationWarmupFoldCount": 0 if is_pi else WARMUP_FOLDS, "nominalCoverage": nominal_coverage,
        "calibrationMethod": "rolling_origin_out_of_fold_absolute_residuals" if is_pi else "prequential_expanding_window_prior_residuals_only",
        "uncertaintyMethod": calibration_result.get("method", "rolling_origin_oof_absolute_residual_v1") if is_pi else METHOD_ID,
        "uncertaintyMethodVersion": calibration_policy.get("policyVersion", "b9.pi-v1") if is_pi else METHOD_VERSION,
        "calibrationStatus": ("governed_available" if calibration_available else "unavailable") if is_p2 else calibration_result["status"],
        "residualCount": len(source_residuals), "foldPlanSha256": calibration_result.get("sourceFoldPlanSha256", calibration_result.get("foldPlanSha256", "0" * 64)),
        "finalQuantileRank": final_quantile_rank, "finalQuantileValue": final_quantile_value,
        "historicalCoverage": None if calibration_metrics is None else calibration_metrics["historicalCoverage" if is_pi else "observed_coverage"],
        "coveredFoldCount": None if calibration_metrics is None else calibration_metrics["coveredFoldCount" if is_pi else "covered_fold_count"],
        "evaluatedFoldCount": None if calibration_metrics is None else calibration_metrics["evaluatedFoldCount" if is_pi else "evaluated_fold_count"],
        "lowerMissCount": None if calibration_metrics is None else calibration_metrics["lowerMissCount" if is_pi else "lower_miss_count"],
        "upperMissCount": None if calibration_metrics is None else calibration_metrics["upperMissCount" if is_pi else "upper_miss_count"],
        "intervalWidthSummary": width_summary, "generatedAt": generated_at,
        "limitations": calibration_limitations, "folds": calibration_result.get("folds", []) if not is_pi else [],
    }
    if is_p2:
        calibration_artifact.update({
            "sourceFamily": "quick_forecast_p2",
            "preprocessingIdentity": assigned_preprocessing_identity,
            "assignmentId": assigned_assignment_id,
            "assignmentCommitSha256": assigned_commit_sha,
            "uncertaintyReasonCode": calibration_reason if is_pi else (None if calibration_available else "model_calibration_unavailable"),
        })
        if is_pi:
            calibration_artifact.update({
            "uncertaintyPolicyId": calibration_policy.get("policyId", "RUNTIME.FORECAST.UNCERTAINTY"),
            "uncertaintyPolicyVersion": calibration_policy.get("policyVersion", "b9.pi-v1"),
            "uncertaintyPolicySha256": calibration_policy.get("policySha256", "0" * 64),
            "sourceAssessmentId": calibration_result.get("sourceAssessmentId"),
            "sourceAssessmentCommitSha256": calibration_result.get("sourceAssessmentCommitSha256"),
            "sourceRollingValidationSha256": calibration_result.get("sourceRollingValidationSha256"),
            "sourceSnapshotClassification": calibration_result.get("sourceSnapshotClassification"),
                "assessmentOofResiduals": source_residuals,
        })
    _write_json_artifact(artifacts / "forecast_calibration.json", calibration_artifact)
    calibration_sha = sha256_file(artifacts / "forecast_calibration.json")
    if calibration_available:
        _update_job(job_path, job, progress="finalizing_empirical_range")
        if is_pi:
            bounds = construct_count_interval(raw, float(final_quantile_value))
            lower_raw, upper_raw = float(bounds["lowerRaw"]), float(bounds["upperRaw"])
            lower_reported, upper_reported = int(bounds["lowerReported"]), int(bounds["upperReported"])
        else:
            bounds = construct_raw_interval(raw, float(final_quantile_value))
            lower_raw, upper_raw = bounds["lower_raw"], bounds["upper_raw"]
            lower_reported, upper_reported = math.floor(lower_raw), math.ceil(upper_raw)
        uncertainty_status = "governed_available" if is_p2 else "available"
        uncertainty_reason_code = None
    else:
        lower_raw = upper_raw = lower_reported = upper_reported = None
        uncertainty_status = "unavailable" if is_p2 else "pending_dataset_specific_calibration"
        uncertainty_reason_code = calibration_reason if is_p2 else "insufficient_residual_folds"

    source_family = "quick_forecast_p2" if is_p2 else "quick_forecast_p1"

    forecast = {
        "schemaVersion": artifact_schema_version, "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "sourceType": "uploaded", "workflowMode": "quick_forecast",
        "activeModelId": assigned_model_id, "modelFamily": assigned_model_family,
        "parameterHash": candidate["parameters_sha256"], "candidateRegistrySha256": registry_hash,
        "policy": policy_identity, "trainingDataIdentity": training_identity, "latestObservedCases": latest_cases,
        "forecastRaw": raw, "forecastReported": reported, "targetPeriod": target_period, "target": TARGET,
        "horizonWeeks": HORIZON_WEEKS, "forecastGrowthCategory": direction,
        "reportingRoundingPolicy": "nearest_integer_python_round_half_to_even", "clippingApplied": raw != published,
        "generatedAt": generated_at, "preparednessAvailability": "unavailable_missing_planning_policy",
        "uncertaintyAvailability": uncertainty_status,
    }
    if is_p2:
        forecast.update({
            "sourceFamily": source_family,
            "preprocessingIdentity": assigned_preprocessing_identity,
            "assignmentId": assigned_assignment_id,
            "assignmentCommitSha256": assigned_commit_sha,
            "lifecyclePolicyId": lifecycle_policy_id,
            "lifecyclePolicyVersion": lifecycle_policy_version,
            "lifecyclePolicySha256": lifecycle_policy_sha,
            "forecastPresentationMode": "point_and_interval" if calibration_available else "point_only",
            "calibrationStatus": "governed_available" if calibration_available else "unavailable",
            "uncertaintyReasonCode": uncertainty_reason_code,
            "deploymentModelAdopted": False,
        })
        if is_p21:
            forecast.update({
                "assignmentAction": assigned_action,
                "authoritySnapshotSha256": authority_snapshot_sha,
            })
    _write_json_artifact(artifacts / "forecast_output.json", forecast)

    uncertainty = {
        "schemaVersion": artifact_schema_version, "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "activeModelId": assigned_model_id,
        "parameterHash": candidate["parameters_sha256"], "uncertaintyStatus": uncertainty_status,
        "lowerRaw": lower_raw, "upperRaw": upper_raw,
        "lowerReported": lower_reported, "upperReported": upper_reported, "isPredictionInterval": bool(is_pi and calibration_available),
        "calibratedOnSyntheticData": bool(calibration_available and not is_pi),
        "nominalCoverage": nominal_coverage if calibration_available else None,
        "historicalCoverage": None if calibration_metrics is None else calibration_metrics["historicalCoverage" if is_pi else "observed_coverage"],
        "calibrationMethod": ("rolling_origin_out_of_fold_absolute_residuals" if is_pi else "prequential_expanding_window_prior_residuals_only") if calibration_available else None,
        "residualCount": len(source_residuals) if calibration_available else (0 if is_p2 else None),
        "coveredFoldCount": None if calibration_metrics is None else calibration_metrics["coveredFoldCount" if is_pi else "covered_fold_count"],
        "calibrationWarmupFoldCount": (0 if is_pi else WARMUP_FOLDS) if calibration_available else None,
        "lowerMissCount": None if calibration_metrics is None else calibration_metrics["lowerMissCount" if is_pi else "lower_miss_count"],
        "upperMissCount": None if calibration_metrics is None else calibration_metrics["upperMissCount" if is_pi else "upper_miss_count"],
        "intervalWidthSummary": width_summary, "uncertaintyMethod": (calibration_result.get("method") if is_pi else METHOD_ID) if calibration_available else None,
        "uncertaintyMethodVersion": (calibration_policy.get("policyVersion") if is_pi else METHOD_VERSION) if calibration_available else None,
        "residualSourceArtifactPath": "artifacts/forecast_calibration.json" if calibration_available else None,
        "residualSourceArtifactSha256": calibration_sha if calibration_available else None,
        "rmseFallbackAllowed": False, "bundledP13RangeReused": False,
        "limitations": calibration_limitations, "generatedAt": generated_at,
    }
    if is_p2:
        uncertainty.update({
            "sourceFamily": source_family,
            "modelFamily": assigned_model_family,
            "preprocessingIdentity": assigned_preprocessing_identity,
            "candidateRegistrySha256": registry_hash,
            "featureOrderSha256": feature_hash,
            "assignmentId": assigned_assignment_id,
            "assignmentCommitSha256": assigned_commit_sha,
            "forecastPresentationMode": "point_and_interval" if calibration_available else "point_only",
            "calibrationStatus": "governed_available" if calibration_available else "unavailable",
            "uncertaintyReasonCode": uncertainty_reason_code,
            **({"calibrationProvenance": ({
                "sourceAssessmentId": calibration_result["sourceAssessmentId"],
                "sourceAssessmentCommitSha256": calibration_result["sourceAssessmentCommitSha256"],
                "sourceRollingValidationSha256": calibration_result["sourceRollingValidationSha256"],
                "candidateId": assigned_model_id,
                "policyId": calibration_policy["policyId"], "policyVersion": calibration_policy["policyVersion"],
                "policySha256": calibration_policy["policySha256"],
                "snapshotClassification": calibration_result["sourceSnapshotClassification"],
            } if calibration_available else None)} if is_pi else {}),
        })
    _write_json_artifact(artifacts / "forecast_uncertainty.json", uncertainty)

    history = [{"period": _period(int(row.epi_year), int(row.epi_week)), "cases": int(row.cases)} for row in cases.tail(52).itertuples()]
    chart = {"schemaVersion": "1.0", "runId": job["runId"], "history": history, "forecast": {"period": target_period, "cases": reported},
        "empiricalRange": {"lower": lower_reported, "upper": upper_reported} if calibration_available else None}
    _write_json_artifact(artifacts / "chart_data.json", chart)

    run_dash = {"runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast", "sourceType": "uploaded",
        "committedAt": generated_at, "completedSteps": 6}
    if is_p2:
        run_dash.update({
            "sourceFamily": source_family,
            "assignmentId": assigned_assignment_id,
            "assignmentCommitSha256": assigned_commit_sha,
        })

    dashboard = {
        "schemaVersion": artifact_schema_version, "run": run_dash,
        "model": {"modelId": assigned_model_id, "modelLabel": assigned_model_family if is_p2 else "Random Forest", "parameterHash": candidate["parameters_sha256"],
            "policyId": policy_identity["id"], "policyVersion": policy_identity["version"],
            "suitabilityStatus": "approved_under_quick_forecast_compatibility_policy", "comparisonPerformed": False},
        "forecast": {"latestObservedCases": latest_cases, "forecastRaw": raw, "forecastReported": reported,
            "targetPeriod": target_period, "target": TARGET, "horizonWeeks": 2, "direction": direction,
            "uncertaintyStatus": uncertainty_status, "empiricalLower": lower_reported, "empiricalUpper": upper_reported,
            "nominalCoverage": nominal_coverage if calibration_available else None,
            "historicalCoverage": None if calibration_metrics is None else calibration_metrics["historicalCoverage" if is_pi else "observed_coverage"],
            "isPredictionInterval": bool(is_pi and calibration_available)},
        "history": history,
        "preparedness": {"availabilityStatus": "unavailable_missing_planning_policy", "scenarios": None, "counts": None, "facilities": [], "alerts": []},
        "evidence": {"validation": {"sha256": job["validationRecordSha256"], "acceptedPeriod": validation.get("acceptedPeriod")},
            "policy": policy_identity, "calibration": {"path": "artifacts/forecast_calibration.json", "sha256": calibration_sha},
            "modelCard": {"path": "artifacts/model_card.json"},
            "provenance": {"datasetId": job["datasetId"], "inputManifest": "artifacts/input_manifest.json"}},
        "limitations": [f"Assigned model {assigned_model_id} used under governed Quick Forecast policy.",
            "No dataset-specific model comparison was performed.", *calibration_limitations,
            "Official preparedness is unavailable because no runtime planning policy is approved."],
    }
    if is_p2:
        dashboard["model"].update({
            "modelFamily": assigned_model_family,
            "preprocessingIdentity": assigned_preprocessing_identity,
            "candidateRegistrySha256": registry_hash,
            "featureOrderSha256": feature_hash,
        })
        dashboard["forecast"].update({
            "forecastPresentationMode": "point_and_interval" if calibration_available else "point_only",
            "calibrationStatus": "governed_available" if calibration_available else "unavailable",
            "uncertaintyReasonCode": uncertainty_reason_code,
        })
        dashboard["evidence"]["lifecyclePolicy"] = {
            "id": lifecycle_policy_id, "version": lifecycle_policy_version, "sha256": lifecycle_policy_sha,
        }
    _write_json_artifact(artifacts / "dashboard_summary.json", dashboard)

    pipeline_summary = {"schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "status": "commit_ready",
        "steps": ["input_revalidated", "features_built", "temporal_calibration_evaluated", "approved_model_trained", "point_forecast_generated", "artifacts_validated"],
        "candidateComparisonPerformed": False, "uncertaintyCalibrationPerformed": calibration_available, "operationalEngineExecuted": False,
        "generatedAt": generated_at}
    _write_json_artifact(artifacts / "pipeline_run_summary.json", pipeline_summary)

    approved_model = {"schemaVersion": "1.0", "modelId": assigned_model_id, "modelFamily": assigned_model_family,
        "parameterHash": candidate["parameters_sha256"], "candidateRegistrySha256": registry_hash, "policy": policy_identity}
    atomic_json(staging / "metadata" / "approved_model.json", approved_model)

    publication_sequence = ["input_manifest.json", "model_features.csv", "forecast_calibration.json", "forecast_output.json", "forecast_uncertainty.json",
        "chart_data.json", "dashboard_summary.json", "pipeline_run_summary.json", "model_card.json"]
    run_record = {"schemaVersion": artifact_schema_version, "runId": job["runId"], "jobId": job["jobId"], "workspaceId": job["workspaceId"],
        "datasetId": job["datasetId"], "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast", "sourceType": "uploaded",
        "status": "commit_ready", "policyId": policy_identity["id"], "policyVersion": policy_identity["version"], "policySha256": policy_hash,
        "createdAt": job["createdAt"], "generatedAt": generated_at, "artifactPublicationSequence": publication_sequence}
    if is_p2:
        run_record.update({
            "sourceFamily": source_family,
            "assignmentId": assigned_assignment_id,
            "assignmentCommitSha256": assigned_commit_sha,
            "activeModelId": assigned_model_id,
            "modelFamily": assigned_model_family,
            "parameterSha256": candidate["parameters_sha256"],
            "preprocessingIdentity": assigned_preprocessing_identity,
            "candidateRegistrySha256": registry_hash,
            "featureOrderSha256": feature_hash,
            "lifecyclePolicyId": lifecycle_policy_id,
            "lifecyclePolicyVersion": lifecycle_policy_version,
            "lifecyclePolicySha256": lifecycle_policy_sha,
        })
        if is_p21:
            run_record.update({
                "assignmentAction": assigned_action,
                "authoritySnapshotSha256": authority_snapshot_sha,
            })
    atomic_json(staging / "metadata" / "run.json", run_record)


    pre_card_names = [name for name in publication_sequence if name != "model_card.json"]
    artifact_hashes = {name: sha256_file(artifacts / name) for name in pre_card_names}
    model_card = {
        "schemaVersion": artifact_schema_version, "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast", "sourceType": "uploaded",
        "model": {"id": assigned_model_id, "family": assigned_model_family, "parameterHash": candidate["parameters_sha256"],
            "candidateRegistrySha256": registry_hash, "runtimeLibrary": candidate.get("estimator_library", "scikit-learn")},
        "features": {"count": 18, "orderSha256": feature_hash}, "target": TARGET, "horizonWeeks": 2,
        "training": training_identity, "policy": policy_identity, "comparisonPerformed": False, "bestModelClaim": False,
        "uncertaintyStatus": uncertainty_status,
        "calibration": {"artifactPath": "artifacts/forecast_calibration.json", "artifactSha256": calibration_sha,
            "status": uncertainty_status, "methodId": (calibration_result.get("method") if is_pi else METHOD_ID) if calibration_available else None,
            "methodVersion": (calibration_policy.get("policyVersion") if is_pi else METHOD_VERSION) if calibration_available else None,
            "residualCount": len(source_residuals) if calibration_available else (0 if is_p2 else None),
            "nominalCoverage": nominal_coverage if calibration_available else None,
            "historicalCoverage": None if calibration_metrics is None else calibration_metrics["historicalCoverage" if is_pi else "observed_coverage"],
            "isPredictionInterval": bool(is_pi and calibration_available), "limitations": calibration_limitations},
        "preparednessStatus": "unavailable_missing_planning_policy",
        "inputHashes": {"originalDengue": validation["files"]["original"]["dengueSha256"], "originalClimate": validation["files"]["original"]["climateSha256"],
            "canonicalDengue": validation["files"]["canonical"]["dengueSha256"], "canonicalClimate": validation["files"]["canonical"]["climateSha256"]},
        "artifactHashes": artifact_hashes, "commitReadiness": "ready_for_runtime_commit",
        "intendedUse": f"Assigned learned model {assigned_model_id} used under governed Quick Forecast policy.",
        "limitations": [f"Execution bound to active assignment for model {assigned_model_id}.",
            "The upload is restricted to the exact synthetic-benchmark-compatible source contract.",
            "Dataset-specific uncertainty calibration is available only when matching calibration residuals exist.",
            "Preparedness outputs are unavailable because no runtime planning policy is approved."],
        "generatedAt": _now(),
    }
    if is_p2:
        model_card["model"]["preprocessingIdentity"] = assigned_preprocessing_identity
        model_card.update({
            "sourceFamily": source_family,
            "assignmentId": assigned_assignment_id,
            "assignmentCommitSha256": assigned_commit_sha,
            "forecastPresentationMode": "point_and_interval" if calibration_available else "point_only",
            "calibrationStatus": "governed_available" if calibration_available else "unavailable",
            "uncertaintyReasonCode": uncertainty_reason_code,
            "deploymentModelAdopted": False,
            "lifecyclePolicy": {
                "id": lifecycle_policy_id, "version": lifecycle_policy_version, "sha256": lifecycle_policy_sha,
            },
        })
        if is_p21:
            model_card.update({
                "assignmentAction": assigned_action,
                "authoritySnapshotSha256": authority_snapshot_sha,
            })
    _update_job(job_path, job, progress="validating_artifacts")
    _write_json_artifact(artifacts / "model_card.json", model_card)
    logs = staging / "logs"
    (logs / "stdout.log").write_text("Quick Forecast analytical artifacts completed; commit validation starting.\n", encoding="utf-8")
    (logs / "stderr.log").write_text("", encoding="utf-8")
    (logs / "events.jsonl").write_text(json.dumps({"timestamp": _now(), "eventType": "artifacts_ready", "runId": job["runId"]}) + "\n", encoding="utf-8")
    _update_job(job_path, job, progress="committing_run")
    committed = commit_runtime_run(runtime_root, staging, job)
    return {"runId": job["runId"], "forecastReported": reported, "committed": True,
            "latest": committed["pointer"]}


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--job-record", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--staging", required=True)
    args = parser.parse_args()
    try:
        result = execute(args)
        print(json.dumps(result, separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "code": "runtime_quick_forecast_failed", "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
