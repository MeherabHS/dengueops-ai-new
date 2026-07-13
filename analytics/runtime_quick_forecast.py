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
from model_factory import build_candidate_estimator, load_and_validate_candidate_registry
from runtime_commit import atomic_json, commit_runtime_run, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_policy import evaluate_quick_forecast_policy, load_and_validate_quick_forecast_policy
from runtime_validate import CONTRACT_VERSION, HORIZON_WEEKS, TARGET, compute_dataset_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _period(year: int, week: int) -> str:
    return f"{year}-W{week:02d}"


def _advance_period(year: int, week: int, amount: int) -> tuple[int, int]:
    ordinal = year * 52 + (week - 1) + amount
    return ordinal // 52, ordinal % 52 + 1


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
    if (policy_hash, policy["policy_id"], policy["policy_version"]) != (job["policySha256"], job["policyId"], job["policyVersion"]):
        raise ValueError("Quick Forecast policy identity changed after queueing.")
    profile = _json(ROOT / "config" / "deployments" / job["deploymentId"] / "profile.json")
    _update_job(job_path, job, progress="building_features")
    cases = pd.read_csv(canonical_case)
    climate = pd.read_csv(canonical_climate)
    training, _ = build_features(canonical_case, canonical_climate, output_path=None)
    inference = build_inference_features(canonical_case, canonical_climate)
    if list(training.loc[:, FEATURE_COLUMNS].columns) != list(FEATURE_COLUMNS) or len(FEATURE_COLUMNS) != 18 or inference.empty:
        raise ValueError("The governed 18-feature contract is unavailable.")
    latest = inference.iloc[-1]
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
        "candidate_registry_sha256": policy["candidate_registry_sha256"],
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
    registry, registry_hash = load_and_validate_candidate_registry()
    if registry_hash != policy["candidate_registry_sha256"]:
        raise ValueError("Candidate registry identity differs from the approved policy.")
    candidate = next(item for item in registry["candidates"] if item["model_id"] == "random_forest")
    if candidate["parameters_sha256"] != policy["approved_model"]["parameters_sha256"]:
        raise ValueError("Approved Random Forest parameter identity mismatch.")
    X = training.loc[:, FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise")
    y = pd.to_numeric(training[TARGET], errors="raise")
    if not np.isfinite(X.to_numpy()).all() or not np.isfinite(y.to_numpy()).all() or (y < 0).any():
        raise ValueError("Training data contains invalid values.")
    inference_row = latest.loc[FEATURE_COLUMNS].to_frame().T.astype(float)
    estimator = build_candidate_estimator("random_forest", registry)
    _update_job(job_path, job, progress="training_approved_model")
    estimator.fit(X, y)
    _update_job(job_path, job, progress="generating_point_forecast")
    raw = float(estimator.predict(inference_row)[0])
    if not math.isfinite(raw) or raw < 0:
        raise ValueError("Random Forest returned an invalid point forecast.")
    published = max(0.0, raw)
    reported = int(round(published))
    latest_cases = int(latest["cases"])
    direction = "Increasing" if reported > latest_cases else "Decreasing" if reported < latest_cases else "Stable"
    target_year, target_week = _advance_period(int(latest["epi_year"]), int(latest["epi_week"]), HORIZON_WEEKS)
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
    (artifacts / "model_features.csv").write_bytes(feature_bytes)
    input_manifest = {
        "schemaVersion": "1.0", "runId": job["runId"], "datasetId": job["datasetId"],
        "validationRecordSha256": job["validationRecordSha256"],
        "originalHashes": validation["files"]["original"], "canonicalHashes": validation["files"]["canonical"],
        "featureOrderSha256": feature_hash, "generatedAt": generated_at,
    }
    _write_json_artifact(artifacts / "input_manifest.json", input_manifest)
    policy_identity = {"id": policy["policy_id"], "version": policy["policy_version"], "sha256": policy_hash}
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
        "uncertaintyAvailability": "pending_dataset_specific_calibration",
    }
    _write_json_artifact(artifacts / "forecast_output.json", forecast)
    uncertainty = {
        "schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
        "deploymentId": job["deploymentId"], "activeModelId": "random_forest", "parameterHash": candidate["parameters_sha256"],
        "uncertaintyStatus": "pending_dataset_specific_calibration", "lowerRaw": None, "upperRaw": None,
        "lowerReported": None, "upperReported": None, "isPredictionInterval": False,
        "calibratedOnSyntheticData": False, "nominalCoverage": None, "historicalCoverage": None,
        "calibrationMethod": None, "residualCount": None, "rmseFallbackAllowed": False,
        "bundledP13RangeReused": False, "limitations": [
            "Dataset-specific temporal calibration has not yet been completed.",
            "No synthetic benchmark range, coverage result, or RMSE fallback is inherited by this uploaded-data forecast.",
        ], "generatedAt": generated_at,
    }
    _write_json_artifact(artifacts / "forecast_uncertainty.json", uncertainty)
    history = [{"period": _period(int(row.epi_year), int(row.epi_week)), "cases": int(row.cases)} for row in cases.tail(52).itertuples()]
    chart = {"schemaVersion": "1.0", "runId": job["runId"], "history": history, "forecast": {"period": target_period, "cases": reported}, "empiricalRange": None}
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
            "uncertaintyStatus": "pending_dataset_specific_calibration", "empiricalLower": None, "empiricalUpper": None},
        "history": history,
        "preparedness": {"availabilityStatus": "unavailable_missing_planning_policy", "scenarios": None, "counts": None, "facilities": [], "alerts": []},
        "evidence": {"validation": {"sha256": job["validationRecordSha256"], "acceptedPeriod": validation.get("acceptedPeriod")},
            "policy": policy_identity, "modelCard": {"path": "artifacts/model_card.json"},
            "provenance": {"datasetId": job["datasetId"], "inputManifest": "artifacts/input_manifest.json"}},
        "limitations": ["Approved deployment model used under the governed Quick Forecast compatibility policy.",
            "No dataset-specific model comparison was performed.", "Uncertainty and preparedness are unavailable for this uploaded-data run."],
    }
    _write_json_artifact(artifacts / "dashboard_summary.json", dashboard)
    pipeline_summary = {"schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "status": "commit_ready",
        "steps": ["input_revalidated", "features_built", "approved_model_trained", "point_forecast_generated", "artifacts_validated"],
        "candidateComparisonPerformed": False, "uncertaintyCalibrationPerformed": False, "operationalEngineExecuted": False,
        "generatedAt": generated_at}
    _write_json_artifact(artifacts / "pipeline_run_summary.json", pipeline_summary)
    approved_model = {"schemaVersion": "1.0", "modelId": "random_forest", "modelFamily": "RandomForestRegressor",
        "parameterHash": candidate["parameters_sha256"], "candidateRegistrySha256": registry_hash, "policy": policy_identity}
    atomic_json(staging / "metadata" / "approved_model.json", approved_model)
    publication_sequence = ["input_manifest.json", "model_features.csv", "forecast_output.json", "forecast_uncertainty.json",
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
        "uncertaintyStatus": "pending_dataset_specific_calibration", "preparednessStatus": "unavailable_missing_planning_policy",
        "inputHashes": {"originalDengue": validation["files"]["original"]["dengueSha256"], "originalClimate": validation["files"]["original"]["climateSha256"],
            "canonicalDengue": validation["files"]["canonical"]["dengueSha256"], "canonicalClimate": validation["files"]["canonical"]["climateSha256"]},
        "artifactHashes": artifact_hashes, "commitReadiness": "ready_for_runtime_commit",
        "intendedUse": "Approved deployment model used under the governed Quick Forecast compatibility policy.",
        "limitations": ["Random Forest is not claimed to be the best model for this uploaded dataset.",
            "The upload is restricted to the exact synthetic-benchmark-compatible source contract.",
            "Dataset-specific uncertainty calibration has not been performed.",
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
