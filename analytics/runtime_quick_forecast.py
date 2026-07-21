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
from model_factory import build_candidate_estimator, load_historical_candidate_registry
from runtime_commit import atomic_json, commit_runtime_run, sha256_file
from runtime_active_model import resolve_active_model
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_policy import evaluate_quick_forecast_policy, load_and_validate_quick_forecast_policy
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
    atomic_json(path, job)


def _write_json_artifact(path: Path, value: Any) -> None:
    atomic_json(path, value)


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
    if "authoritySnapshotSha256" in job:
        authority=resolve_active_model(ROOT,runtime_root,job["deploymentId"])
        if authority["authoritySnapshotSha256"]!=job["authoritySnapshotSha256"] or authority["modelId"]!=job.get("resolvedModelId") or authority["modelFamily"]!=job.get("resolvedModelFamily") or authority["parameterSha256"]!=job.get("resolvedModelParameterSha256") or authority["featureOrderSha256"]!=job.get("resolvedFeatureOrderSha256") or authority["candidateRegistrySha256"]!=job.get("resolvedCandidateRegistrySha256") or authority["quickPolicySha256"]!=job.get("quickPolicySha256"):
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

    policy, policy_hash = load_and_validate_quick_forecast_policy(job["deploymentId"])
    is_p2 = policy.get("schemaVersion") == "2.0" or policy.get("requiresActiveAssignment") is True
    profile = _json(ROOT / "config" / "deployments" / job["deploymentId"] / "profile.json")

    assigned_model_id = "random_forest"
    active_authority = None
    if is_p2:
        try:
            active_authority = resolve_active_model(ROOT, runtime_root, job["deploymentId"])
        except Exception as exc:
            raise ValueError(f"active_model_not_assigned: {exc}") from exc
        if active_authority.get("authoritySource") != "committed_assignment":
            raise ValueError("active_model_not_assigned")
        assigned_model_id = active_authority.get("modelId")

    _update_job(job_path, job, progress="building_features")
    cases = pd.read_csv(canonical_case)
    climate = pd.read_csv(canonical_climate)
    training, _ = build_features(canonical_case, canonical_climate, output_path=None)
    inference = build_inference_features(canonical_case, canonical_climate)
    if list(training.loc[:, FEATURE_COLUMNS].columns) != list(FEATURE_COLUMNS) or len(FEATURE_COLUMNS) != 18 or inference.empty:
        raise ValueError("The governed 18-feature contract is unavailable.")
    latest = inference.iloc[-1]

    if not is_p2:
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
    registry, registry_hash = load_historical_candidate_registry()
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
    policy_identity = {"id": policy["policy_id"], "version": policy["policy_version"], "sha256": policy_hash}
    available_fold_count = max(0, len(training) - INITIAL_TRAINING_ROWS - EMBARGO_ROWS)
    calibration_limitations = ([
        "The empirical range uses only dataset-specific out-of-sample Random Forest rolling-origin residuals.",
        "Targets overlap and residuals are temporally dependent; historical coverage does not guarantee future coverage.",
        "The range is not a probability statement or prediction interval.",
        "The currently governed uploaded source scope is deterministic synthetic benchmark data.",
        "Preparedness scenarios, bundled bounds, and RMSE sensitivity are not calibration inputs.",
    ] if calibration_available else [
        f"Dataset-specific calibration requires exactly 68 complete residual folds; this dataset provides {available_fold_count}.",
        "No partial residual pool, benchmark range, preparedness scenario, or RMSE fallback was used.",
    ])
    width_summary = None if calibration_metrics is None else {
        "average": calibration_metrics["average_interval_width"],
        "median": calibration_metrics["median_interval_width"],
        "minimum": calibration_metrics["minimum_interval_width"],
        "maximum": calibration_metrics["maximum_interval_width"],
    }
    calibration_artifact = {
        "schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentProfileId": job["deploymentId"], "policyId": policy["policy_id"], "policyVersion": policy["policy_version"],
        "policySha256": policy_hash, "modelId": "random_forest", "modelFamily": "RandomForestRegressor",
        "modelParametersSha256": candidate["parameters_sha256"], "candidateRegistrySha256": registry_hash,
        "featureOrder": list(FEATURE_COLUMNS), "featureOrderSha256": feature_hash, "targetColumn": TARGET,
        "forecastHorizonWeeks": CALIBRATION_HORIZON_WEEKS, "initialTrainingRows": INITIAL_TRAINING_ROWS,
        "embargoRows": EMBARGO_ROWS, "foldStepRows": FOLD_STEP_ROWS, "requiredResidualCount": REQUIRED_RESIDUALS,
        "calibrationWarmupFoldCount": WARMUP_FOLDS, "nominalCoverage": NOMINAL_COVERAGE,
        "calibrationMethod": "prequential_expanding_window_prior_residuals_only", "uncertaintyMethod": METHOD_ID,
        "uncertaintyMethodVersion": METHOD_VERSION, "calibrationStatus": calibration_result["status"],
        "residualCount": len(calibration_result["folds"]), "foldPlanSha256": calibration_result["foldPlanSha256"],
        "finalQuantileRank": final_quantile_rank, "finalQuantileValue": final_quantile_value,
        "historicalCoverage": None if calibration_metrics is None else calibration_metrics["observed_coverage"],
        "coveredFoldCount": None if calibration_metrics is None else calibration_metrics["covered_fold_count"],
        "evaluatedFoldCount": None if calibration_metrics is None else calibration_metrics["evaluated_fold_count"],
        "lowerMissCount": None if calibration_metrics is None else calibration_metrics["lower_miss_count"],
        "upperMissCount": None if calibration_metrics is None else calibration_metrics["upper_miss_count"],
        "intervalWidthSummary": width_summary, "generatedAt": generated_at,
        "limitations": calibration_limitations, "folds": calibration_result["folds"],
    }
    _write_json_artifact(artifacts / "forecast_calibration.json", calibration_artifact)
    calibration_sha = sha256_file(artifacts / "forecast_calibration.json")
    if calibration_available:
        _update_job(job_path, job, progress="finalizing_empirical_range")
        bounds = construct_raw_interval(raw, float(final_quantile_value))
        lower_raw, upper_raw = bounds["lower_raw"], bounds["upper_raw"]
        lower_reported, upper_reported = math.floor(lower_raw), math.ceil(upper_raw)
        uncertainty_status = "available"
    else:
        lower_raw = upper_raw = lower_reported = upper_reported = None
        uncertainty_status = "pending_dataset_specific_calibration"
    forecast = {
        "schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "sourceType": "uploaded", "workflowMode": "quick_forecast",
        "activeModelId": "random_forest", "modelFamily": "RandomForestRegressor",
        "parameterHash": candidate["parameters_sha256"], "candidateRegistrySha256": registry_hash,
        "policy": policy_identity, "trainingDataIdentity": training_identity, "latestObservedCases": latest_cases,
        "forecastRaw": raw, "forecastReported": reported, "targetPeriod": target_period, "target": TARGET,
        "horizonWeeks": HORIZON_WEEKS, "forecastGrowthCategory": direction,
        "reportingRoundingPolicy": "nearest_integer_python_round_half_to_even", "clippingApplied": raw != published,
        "generatedAt": generated_at, "preparednessAvailability": "unavailable_missing_planning_policy",
        "uncertaintyAvailability": uncertainty_status,
    }
    _write_json_artifact(artifacts / "forecast_output.json", forecast)
    uncertainty = {
        "schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "activeModelId": "random_forest", "parameterHash": candidate["parameters_sha256"],
        "uncertaintyStatus": uncertainty_status, "lowerRaw": lower_raw, "upperRaw": upper_raw,
        "lowerReported": lower_reported, "upperReported": upper_reported, "isPredictionInterval": False,
        "calibratedOnSyntheticData": calibration_available,
        "nominalCoverage": NOMINAL_COVERAGE if calibration_available else None,
        "historicalCoverage": None if calibration_metrics is None else calibration_metrics["observed_coverage"],
        "calibrationMethod": "prequential_expanding_window_prior_residuals_only" if calibration_available else None,
        "residualCount": REQUIRED_RESIDUALS if calibration_available else None,
        "coveredFoldCount": None if calibration_metrics is None else calibration_metrics["covered_fold_count"],
        "calibrationWarmupFoldCount": WARMUP_FOLDS if calibration_available else None,
        "lowerMissCount": None if calibration_metrics is None else calibration_metrics["lower_miss_count"],
        "upperMissCount": None if calibration_metrics is None else calibration_metrics["upper_miss_count"],
        "intervalWidthSummary": width_summary, "uncertaintyMethod": METHOD_ID if calibration_available else None,
        "uncertaintyMethodVersion": METHOD_VERSION if calibration_available else None,
        "residualSourceArtifactPath": "artifacts/forecast_calibration.json" if calibration_available else None,
        "residualSourceArtifactSha256": calibration_sha if calibration_available else None,
        "rmseFallbackAllowed": False, "bundledP13RangeReused": False,
        "limitations": calibration_limitations, "generatedAt": generated_at,
    }
    _write_json_artifact(artifacts / "forecast_uncertainty.json", uncertainty)
    history = [{"period": _period(int(row.epi_year), int(row.epi_week)), "cases": int(row.cases)} for row in cases.tail(52).itertuples()]
    chart = {"schemaVersion": "1.0", "runId": job["runId"], "history": history, "forecast": {"period": target_period, "cases": reported},
        "empiricalRange": {"lower": lower_reported, "upper": upper_reported} if calibration_available else None}
    _write_json_artifact(artifacts / "chart_data.json", chart)
    dashboard = {
        "schemaVersion": "1.0", "run": {"runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
            "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast", "sourceType": "uploaded",
            "committedAt": generated_at, "completedSteps": 6},
        "model": {"modelId": "random_forest", "modelLabel": "Random Forest", "parameterHash": candidate["parameters_sha256"],
            "policyId": policy["policy_id"], "policyVersion": policy["policy_version"],
            "suitabilityStatus": "approved_under_quick_forecast_compatibility_policy", "comparisonPerformed": False},
        "forecast": {"latestObservedCases": latest_cases, "forecastRaw": raw, "forecastReported": reported,
            "targetPeriod": target_period, "target": TARGET, "horizonWeeks": 2, "direction": direction,
            "uncertaintyStatus": uncertainty_status, "empiricalLower": lower_reported, "empiricalUpper": upper_reported,
            "nominalCoverage": NOMINAL_COVERAGE if calibration_available else None,
            "historicalCoverage": None if calibration_metrics is None else calibration_metrics["observed_coverage"],
            "isPredictionInterval": False},
        "history": history,
        "preparedness": {"availabilityStatus": "unavailable_missing_planning_policy", "scenarios": None, "counts": None, "facilities": [], "alerts": []},
        "evidence": {"validation": {"sha256": job["validationRecordSha256"], "acceptedPeriod": validation.get("acceptedPeriod")},
            "policy": policy_identity, "calibration": {"path": "artifacts/forecast_calibration.json", "sha256": calibration_sha},
            "modelCard": {"path": "artifacts/model_card.json"},
            "provenance": {"datasetId": job["datasetId"], "inputManifest": "artifacts/input_manifest.json"}},
        "limitations": ["Approved deployment model used under the governed Quick Forecast compatibility policy.",
            "No dataset-specific model comparison was performed.", *calibration_limitations,
            "Official preparedness is unavailable because no runtime planning policy is approved."],
    }
    _write_json_artifact(artifacts / "dashboard_summary.json", dashboard)
    pipeline_summary = {"schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "status": "commit_ready",
        "steps": ["input_revalidated", "features_built", "temporal_calibration_evaluated", "approved_model_trained", "point_forecast_generated", "artifacts_validated"],
        "candidateComparisonPerformed": False, "uncertaintyCalibrationPerformed": calibration_available, "operationalEngineExecuted": False,
        "generatedAt": generated_at}
    _write_json_artifact(artifacts / "pipeline_run_summary.json", pipeline_summary)
    approved_model = {"schemaVersion": "1.0", "modelId": "random_forest", "modelFamily": "RandomForestRegressor",
        "parameterHash": candidate["parameters_sha256"], "candidateRegistrySha256": registry_hash, "policy": policy_identity}
    atomic_json(staging / "metadata" / "approved_model.json", approved_model)
    publication_sequence = ["input_manifest.json", "model_features.csv", "forecast_calibration.json", "forecast_output.json", "forecast_uncertainty.json",
        "chart_data.json", "dashboard_summary.json", "pipeline_run_summary.json", "model_card.json"]
    run_record = {"schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "workspaceId": job["workspaceId"],
        "datasetId": job["datasetId"], "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast", "sourceType": "uploaded",
        "status": "commit_ready", "policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_hash,
        "createdAt": job["createdAt"], "generatedAt": generated_at, "artifactPublicationSequence": publication_sequence}
    atomic_json(staging / "metadata" / "run.json", run_record)

    pre_card_names = [name for name in publication_sequence if name != "model_card.json"]
    artifact_hashes = {name: sha256_file(artifacts / name) for name in pre_card_names}
    model_card = {
        "schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "workflowMode": "quick_forecast", "sourceType": "uploaded",
        "model": {"id": "random_forest", "family": "RandomForestRegressor", "parameterHash": candidate["parameters_sha256"],
            "candidateRegistrySha256": registry_hash, "runtimeLibrary": "scikit-learn"},
        "features": {"count": 18, "orderSha256": feature_hash}, "target": TARGET, "horizonWeeks": 2,
        "training": training_identity, "policy": policy_identity, "comparisonPerformed": False, "bestModelClaim": False,
        "uncertaintyStatus": uncertainty_status,
        "calibration": {"artifactPath": "artifacts/forecast_calibration.json", "artifactSha256": calibration_sha,
            "status": uncertainty_status, "methodId": METHOD_ID if calibration_available else None,
            "methodVersion": METHOD_VERSION if calibration_available else None,
            "residualCount": REQUIRED_RESIDUALS if calibration_available else None,
            "nominalCoverage": NOMINAL_COVERAGE if calibration_available else None,
            "historicalCoverage": None if calibration_metrics is None else calibration_metrics["observed_coverage"],
            "isPredictionInterval": False, "limitations": calibration_limitations},
        "preparednessStatus": "unavailable_missing_planning_policy",
        "inputHashes": {"originalDengue": validation["files"]["original"]["dengueSha256"], "originalClimate": validation["files"]["original"]["climateSha256"],
            "canonicalDengue": validation["files"]["canonical"]["dengueSha256"], "canonicalClimate": validation["files"]["canonical"]["climateSha256"]},
        "artifactHashes": artifact_hashes, "commitReadiness": "ready_for_runtime_commit",
        "intendedUse": "Approved deployment model used under the governed Quick Forecast compatibility policy.",
        "limitations": ["Random Forest is not claimed to be the best model for this uploaded dataset.",
            "The upload is restricted to the exact synthetic-benchmark-compatible source contract.",
            "Dataset-specific uncertainty calibration is available only when exactly 68 complete folds are validated.",
            "Preparedness outputs are unavailable because no runtime planning-scenario policy is approved."],
        "generatedAt": _now(),
    }
    _update_job(job_path, job, progress="validating_artifacts")
    _write_json_artifact(artifacts / "model_card.json", model_card)
    logs = staging / "logs"
    (logs / "stdout.log").write_text("Quick Forecast analytical artifacts completed; commit validation starting.\n", encoding="utf-8")
    (logs / "stderr.log").write_text("", encoding="utf-8")
    (logs / "events.jsonl").write_text(json.dumps({"timestamp": _now(), "eventType": "artifacts_ready", "runId": job["runId"]}) + "\n", encoding="utf-8")
    _update_job(job_path, job, status="committing", progress="committing_run")
    committed = commit_runtime_run(runtime_root, staging, job)
    return {"runId": job["runId"], "forecastReported": reported, "committed": True, "latest": committed["pointer"]}


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
