"""Execute one governed dataset assessment in isolated runtime storage."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker
from sklearn.exceptions import ConvergenceWarning

from feature_engineering import FEATURE_COLUMNS, build_features
from model_factory import build_candidate_estimator, load_and_validate_candidate_registry
from runtime_assessment_commit import commit_runtime_assessment
from runtime_assessment_evidence import (
    aggregate_candidate,
    failed_prediction,
    fold_plan_sha256,
    matrix_sha256,
    prediction_evidence,
    selection_eligible,
    select_technical_winner,
)
from runtime_assessment_policy import evaluate_assessment_policy, load_and_validate_assessment_policy
from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_validate import CONTRACT_VERSION, HORIZON_WEEKS, TARGET, compute_dataset_id


CANDIDATE_IDS = (
    "previous_week_naive", "moving_average_4w", "seasonal_naive_52w",
    "ridge_regression", "poisson_regression", "random_forest", "gradient_boosting",
)
LEARNED_IDS = {"ridge_regression", "poisson_regression", "random_forest", "gradient_boosting"}
BASELINE_IDS = set(CANDIDATE_IDS) - LEARNED_IDS
SCHEMAS = {
    "rolling_validation.json": "runtime_rolling_validation.schema.json",
    "candidate_model_comparison.json": "runtime_candidate_comparison.schema.json",
    "recommendation.json": "runtime_recommendation.schema.json",
    "assessment_summary.json": "runtime_assessment_summary.schema.json",
    "assessment.json": "runtime_assessment.schema.json",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object.")
    return value


def _period(row: Mapping[str, Any] | pd.Series) -> str:
    return f"{int(row['epi_year'])}-W{int(row['epi_week']):02d}"


def _advance_period(row: Mapping[str, Any] | pd.Series, weeks: int) -> str:
    monday = date.fromisocalendar(int(row["epi_year"]), int(row["epi_week"]), 1) + timedelta(weeks=weeks)
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


def _matrix_sha(frame: pd.DataFrame) -> str:
    return matrix_sha256(frame.to_dict("records"), FEATURE_COLUMNS, TARGET)


def _single(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame:
        return None
    values = {str(value).strip() for value in frame[column].tolist() if str(value).strip()}
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


def build_common_fold_plan(frame: pd.DataFrame, policy: Mapping[str, Any]) -> tuple[tuple[dict[str, Any], ...], str]:
    ordered = frame.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    fold_policy = policy["fold_policy"]
    if len(ordered) != 173 or ordered[["epi_year", "epi_week"]].duplicated().any():
        raise ValueError("The active assessment policy requires exactly 173 unique labelled rows.")
    if list(ordered.index) != list(range(173)) or any(int(value) == 53 for value in ordered["epi_week"]):
        raise ValueError("The labelled feature matrix violates governed chronology.")
    first = int(fold_policy["initial_training_rows"]) + int(fold_policy["embargo_rows"])
    descriptors: list[dict[str, Any]] = []
    for sequence, validation_index in enumerate(range(first, len(ordered), int(fold_policy["step_size_weeks"])), 1):
        train_end = validation_index - int(fold_policy["embargo_rows"])
        train = ordered.iloc[:train_end]
        validation = ordered.iloc[validation_index]
        embargo = ordered.iloc[validation_index - 1]
        origin = _period(validation)
        target_period = _advance_period(validation, HORIZON_WEEKS)
        trajectory = "rising" if float(validation[TARGET]) > float(validation["cases"]) else "declining" if float(validation[TARGET]) < float(validation["cases"]) else "stable"
        descriptors.append({
            "foldId": f"rolling-origin-{sequence:04d}-{origin}-to-{target_period}",
            "sequence": sequence, "trainStartIndex": 0, "trainEndExclusive": train_end,
            "embargoIndex": validation_index - 1, "validationIndex": validation_index,
            "trainingPeriod": {"start": _period(train.iloc[0]), "end": _period(train.iloc[-1])},
            "trainingRowCount": len(train), "embargoPeriod": _period(embargo),
            "forecastOrigin": origin, "targetPeriod": target_period, "actualTarget": float(validation[TARGET]),
            "targetTrajectory": trajectory, "featureOrderSha256": policy["feature_contract"]["feature_order_sha256"],
            "trainingMatrixSha256": _matrix_sha(train),
            "validationMatrixSha256": _matrix_sha(validation.to_frame().T),
            "labelAvailabilityRule": fold_policy["label_availability_rule"],
        })
    if len(descriptors) != 68:
        raise ValueError("The governed assessment must produce exactly 68 folds.")
    return tuple(descriptors), fold_plan_sha256(descriptors)


def _prediction(model_id: str, actual: float, raw: float, runtime: float, warning_codes: list[str]) -> dict[str, Any]:
    return prediction_evidence(model_id, actual, raw, runtime, warning_codes)


def _failed(model_id: str, reason: str, runtime: float = 0.0, warnings_: list[str] | None = None) -> dict[str, Any]:
    return failed_prediction(model_id, reason, runtime, warnings_)


def _aggregate(records: list[dict[str, Any]], actuals: list[float]) -> dict[str, Any] | None:
    return aggregate_candidate(records, actuals)


def _schema_validate(value: dict[str, Any], schema_name: str) -> None:
    schema = _json(ROOT / "config" / schema_name)
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=lambda item: list(item.path))
    if errors:
        raise ValueError(f"{schema_name}: {errors[0].message}")


def execute(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root = require_absolute_directory(args.runtime_root, "runtime root")
    job_path = require_within(runtime_root, args.job_record, "job record")
    workspace = require_within(runtime_root, args.workspace, "workspace")
    staging = require_within(runtime_root, args.staging, "assessment staging")
    if workspace.parent != (runtime_root / "workspaces").resolve() or staging.parent != (runtime_root / "assessment-staging").resolve():
        raise ValueError("Assessment execution paths have invalid parents.")
    job = _json(job_path)
    if job.get("status") != "running" or job.get("jobKind") != "dataset_assessment" or job.get("workflowMode") != "assess_dataset":
        raise ValueError("The claimed job is not a runnable dataset assessment.")
    if staging.name != job["assessmentId"] or workspace.name != job["workspaceId"]:
        raise ValueError("Assessment paths do not match job identities.")

    metadata = _json(workspace / "metadata" / "workspace.json")
    validation_path = workspace / "metadata" / "validation.json"
    validation_bytes = validation_path.read_bytes()
    validation = json.loads(validation_bytes.decode("utf-8"))
    if hashlib.sha256(validation_bytes).hexdigest() != job["validationRecordSha256"]:
        raise ValueError("The authoritative validation record changed after queueing.")
    if metadata.get("status") != "ready" or metadata.get("workflowMode") != "assess_dataset" or metadata.get("datasetId") != job["datasetId"]:
        raise ValueError("The assessment workspace is no longer ready.")
    canonical_case = workspace / "inputs" / "canonical" / "dengue_cases.csv"
    canonical_climate = workspace / "inputs" / "canonical" / "climate_data.csv"
    if sha256_file(canonical_case) != validation["files"]["canonical"]["dengueSha256"] or sha256_file(canonical_climate) != validation["files"]["canonical"]["climateSha256"]:
        raise ValueError("Canonical uploaded files changed after validation.")
    feature_hash = validation["datasetIdentity"]["featureOrderSha256"]
    if compute_dataset_id(canonical_case.read_bytes(), canonical_climate.read_bytes(), job["deploymentId"], feature_hash) != job["datasetId"]:
        raise ValueError("Dataset identity could not be recomputed.")

    policy, policy_hash = load_and_validate_assessment_policy(job["deploymentId"])
    registry, registry_hash = load_and_validate_candidate_registry()
    if (policy["policy_id"], policy["policy_version"], policy_hash, registry_hash) != (
        job["assessmentPolicyId"], job["assessmentPolicyVersion"], job["assessmentPolicySha256"], job["candidateRegistrySha256"],
    ):
        raise ValueError("Assessment governance identity changed after queueing.")
    cases = pd.read_csv(canonical_case)
    climate = pd.read_csv(canonical_climate)
    source_metadata = {
        "cases": {"source_type": _single(cases, "source_type"), "aggregation_method": "weekly_epi_week_case_count", "contains_approximated_values": _approximated(cases)},
        "climate": {"source_type": _single(climate, "source_type"), "aggregation_method": _single(climate, "aggregation_method"), "contains_approximated_values": _approximated(climate)},
    }
    assessment_policy_result = evaluate_assessment_policy(policy, {
        "validation_passed": validation.get("status") == "ready", "deployment_id": job["deploymentId"],
        "case_geography": validation["datasetIdentity"].get("geography"), "climate_geography": validation["datasetIdentity"].get("geography"),
        "canonical_contract_version": validation["normalization"]["canonicalContractVersion"],
        "feature_order_sha256": feature_hash, "constructible_feature_count": 18, "target": validation["datasetIdentity"]["target"],
        "horizon_weeks": validation["datasetIdentity"]["horizonWeeks"], "source_metadata": source_metadata,
        "labelled_rows": validation["counts"]["labelledRows"], "available_history_weeks": validation["counts"]["overlapWeeks"],
        "candidate_registry": registry, "candidate_registry_sha256": registry_hash,
        "chronological_order_valid": True, "duplicate_periods_absent": True, "contiguous_history": True, "case_climate_aligned": True,
    })
    if not assessment_policy_result["eligible"] or assessment_policy_result["assessmentStatus"] != "full_assessment_eligible" \
            or assessment_policy_result["plannedFoldCount"] != 68 or validation["counts"]["labelledRows"] != 173:
        raise ValueError(f"The workspace is no longer eligible for full dataset assessment: {assessment_policy_result['reasonCodes']}")

    _update_job(job_path, job, progress="preparing_assessment")
    for relative in ("metadata", "inputs/original", "inputs/canonical", "artifacts"):
        (staging / relative).mkdir(parents=True, exist_ok=True)
    for source, target in (
        (workspace / "inputs/original/dengue.csv", staging / "inputs/original/dengue.csv"),
        (workspace / "inputs/original/climate.csv", staging / "inputs/original/climate.csv"),
        (canonical_case, staging / "inputs/canonical/dengue_cases.csv"),
        (canonical_climate, staging / "inputs/canonical/climate_data.csv"),
        (validation_path, staging / "metadata/validation.json"),
    ):
        shutil.copy2(source, target)
    atomic_json(staging / "metadata/policy.json", policy)

    _update_job(job_path, job, progress="building_features")
    frame, _ = build_features(canonical_case, canonical_climate, output_path=None)
    if len(frame) != 173 or list(frame.loc[:, FEATURE_COLUMNS].columns) != list(FEATURE_COLUMNS) or not np.isfinite(frame[FEATURE_COLUMNS + [TARGET]].to_numpy(float)).all():
        raise ValueError("The governed 173-row, 18-feature assessment matrix is unavailable.")
    feature_path = staging / "artifacts/model_features.csv"
    frame.to_csv(feature_path, index=False, lineterminator="\n")
    generated_at = _now()
    manifest = {
        "schemaVersion": "1.0", "assessmentId": job["assessmentId"], "jobId": job["jobId"],
        "workspaceId": job["workspaceId"], "datasetId": job["datasetId"], "deploymentId": job["deploymentId"],
        "validationRecordSha256": job["validationRecordSha256"], "originalHashes": validation["files"]["original"],
        "canonicalHashes": validation["files"]["canonical"], "featureOrderSha256": feature_hash,
        "modelFeaturesSha256": sha256_file(feature_path), "generatedAt": generated_at,
    }
    atomic_json(staging / "artifacts/input_manifest.json", manifest)

    _update_job(job_path, job, progress="creating_fold_plan")
    plan, plan_hash = build_common_fold_plan(frame, policy)
    if plan[0]["foldId"] != "rolling-origin-0001-2023-W07-to-2023-W09" or plan[-1]["foldId"] != "rolling-origin-0068-2024-W22-to-2024-W24":
        raise ValueError("The common fold plan differs from governed boundary identities.")
    frozen_plan_hash = plan_hash
    _update_job(job_path, job, progress="checking_candidate_eligibility")
    eligibility = assessment_policy_result["candidateEligibility"]
    case_lookup = {f"{int(row.epi_year)}-W{int(row.epi_week):02d}": float(row.cases) for row in cases.itertuples()}
    predictions: dict[str, list[dict[str, Any]]] = {model_id: [] for model_id in CANDIDATE_IDS}
    actuals = [float(descriptor["actualTarget"]) for descriptor in plan]
    registry_by_id = {candidate["model_id"]: candidate for candidate in registry["candidates"]}

    for model_id in CANDIDATE_IDS:
        _update_job(job_path, job, progress=f"evaluating_{model_id}")
        if fold_plan_sha256(plan) != frozen_plan_hash:
            raise ValueError("The common fold plan changed before candidate execution.")
        preflight = eligibility[model_id]
        if not preflight["eligible"]:
            reason = preflight["reasonCodes"][0] if preflight["reasonCodes"] else "candidate_preflight_ineligible"
            predictions[model_id] = [_failed(model_id, reason) for _ in plan]
            continue
        for descriptor in plan:
            started = time.perf_counter()
            warning_codes: list[str] = []
            try:
                validation_row = frame.iloc[descriptor["validationIndex"]]
                if model_id == "previous_week_naive":
                    raw = float(validation_row["cases_lag_1w"])
                elif model_id == "moving_average_4w":
                    raw = float(validation_row["cases_rolling_4w"])
                elif model_id == "seasonal_naive_52w":
                    target_monday = date.fromisocalendar(int(validation_row["epi_year"]), int(validation_row["epi_week"]), 1) + timedelta(weeks=HORIZON_WEEKS - 52)
                    year, week, _ = target_monday.isocalendar()
                    source_period = f"{year}-W{week:02d}"
                    if source_period not in case_lookup:
                        raise ValueError("seasonal_source_missing")
                    raw = case_lookup[source_period]
                else:
                    train = frame.iloc[descriptor["trainStartIndex"]:descriptor["trainEndExclusive"]]
                    x_train = train[FEATURE_COLUMNS].to_numpy(float)
                    y_train = train[TARGET].to_numpy(float)
                    x_valid = validation_row[FEATURE_COLUMNS].to_numpy(float).reshape(1, -1)
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter("always")
                        estimator = build_candidate_estimator(model_id, registry)
                        estimator.fit(x_train, y_train)
                        raw = float(estimator.predict(x_valid)[0])
                    warning_codes = [item.category.__name__ for item in caught]
                    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
                        raise ValueError("convergence_failure")
                predictions[model_id].append(_prediction(model_id, descriptor["actualTarget"], raw, time.perf_counter() - started, warning_codes))
            except Exception as exc:
                reason = str(exc) if str(exc) in {"seasonal_source_missing", "convergence_failure", "nonfinite_prediction", "prohibited_negative_prediction"} else "candidate_execution_failed"
                predictions[model_id].append(_failed(model_id, reason, time.perf_counter() - started, warning_codes))
        if fold_plan_sha256(plan) != frozen_plan_hash:
            raise ValueError("Candidate execution changed the common fold plan.")

    _update_job(job_path, job, progress="aggregating_metrics")
    candidate_results: list[dict[str, Any]] = []
    for model_id in CANDIDATE_IDS:
        records = predictions[model_id]
        successful = sum(record["foldStatus"] in {"success", "warning"} for record in records)
        failed = len(records) - successful
        metrics = _aggregate(records, actuals)
        preflight = eligibility[model_id]
        candidate = registry_by_id[model_id]
        candidate_results.append({
            "modelId": model_id, "modelLabel": candidate["model_family"],
            "candidateClass": preflight["candidateClass"], "deployabilityClass": preflight["deployabilityClassification"],
            "parametersSha256": candidate["parameters_sha256"], "eligible": preflight["eligible"],
            "completionStatus": "complete" if successful == 68 and failed == 0 else "ineligible" if not preflight["eligible"] else "incomplete",
            "reasonCodes": preflight["reasonCodes"] if not preflight["eligible"] else sorted({record["failureReasonCode"] for record in records if record["failureReasonCode"]}) or ["candidate_completed_all_folds"],
            "reasons": preflight["reasons"] if not preflight["eligible"] else (["Candidate completed every fold in the immutable common plan."] if failed == 0 else ["Candidate did not complete every fold and is not selection eligible."]),
            "successfulFolds": successful, "failedFolds": failed,
            "selectionEligible": selection_eligible(
                policy_eligible=bool(preflight["eligible"]), successful_folds=successful,
                failed_folds=failed, metrics=metrics,
            ),
            "selectionComplexityRank": candidate["selection_complexity_rank"], "metrics": metrics,
            "executionMode": "fitted_per_fold" if model_id in LEARNED_IDS else "deterministic_baseline_per_fold",
            "historicalPredictionsReused": False,
        })
    complete = [candidate for candidate in candidate_results if candidate["selectionEligible"]]
    baseline_ok = any(candidate["modelId"] in BASELINE_IDS for candidate in complete)
    learned_ok = any(candidate["modelId"] in LEARNED_IDS for candidate in complete)
    if len(complete) < 2 or not baseline_ok or not learned_ok:
        candidate_set_status = "insufficient_candidate_breadth"
    elif len(complete) == 7:
        candidate_set_status = "complete_candidate_set"
    else:
        candidate_set_status = "partial_candidate_set"

    _update_job(job_path, job, progress="selecting_technical_winner")
    winner, tie_stage, tie_steps, selection_ids = select_technical_winner(candidate_results) if baseline_ok and learned_ok else (None, None, [], [])
    winner_candidate = next((candidate for candidate in candidate_results if candidate["modelId"] == winner), None)
    runner_up = sorted((candidate for candidate in complete if candidate["modelId"] != winner), key=lambda item: item["metrics"]["mae"])[0] if winner and len(complete) > 1 else None
    if winner:
        winner_records = {descriptor["foldId"]: predictions[winner][index] for index, descriptor in enumerate(plan)}
        for candidate in candidate_results:
            better = tied = worse = 0
            for index, descriptor in enumerate(plan):
                record = predictions[candidate["modelId"]][index]
                selected = winner_records[descriptor["foldId"]]
                if record["absoluteError"] is None or selected["absoluteError"] is None:
                    continue
                difference = record["absoluteError"] - selected["absoluteError"]
                better += difference < -1e-9
                tied += abs(difference) <= 1e-9
                worse += difference > 1e-9
            candidate["foldWinsTiesLosses"] = {"better": better, "tied": tied, "worse": worse}
    else:
        for candidate in candidate_results:
            candidate["foldWinsTiesLosses"] = None

    fold_values = []
    for index, descriptor in enumerate(plan):
        fold_values.append({
            **{key: value for key, value in descriptor.items() if key not in {"trainStartIndex", "trainEndExclusive", "embargoIndex", "validationIndex"}},
            "predictions": [predictions[model_id][index] for model_id in CANDIDATE_IDS],
        })
    rolling = {
        "schemaVersion": "1.0", "assessmentId": job["assessmentId"], "jobId": job["jobId"], "workspaceId": job["workspaceId"],
        "datasetId": job["datasetId"], "deploymentId": job["deploymentId"],
        "assessmentPolicy": {"policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_hash},
        "candidateRegistrySha256": registry_hash, "foldPolicy": {
            "policyId": policy["fold_policy"]["policy_id"], "policyVersion": policy["fold_policy"]["policy_version"],
            "trainingWindow": "expanding", "initialTrainingRows": 104, "embargoRows": 1,
            "validationRowsPerFold": 1, "stepSizeWeeks": 1, "samePlanForAllCandidates": True,
        }, "foldPlanSha256": plan_hash, "plannedFoldCount": 68, "candidateIds": list(CANDIDATE_IDS),
        "featureOrderSha256": feature_hash, "target": TARGET, "horizonWeeks": 2, "folds": fold_values,
        "generatedAt": generated_at,
    }
    rolling_path = staging / "artifacts/rolling_validation.json"
    atomic_json(rolling_path, rolling)
    rolling_hash = sha256_file(rolling_path)
    selection_reason = f"{winner} had the lowest governed metric sequence among candidates completing all 68 folds." if winner else "No technical winner satisfied the governed completeness and breadth requirements."
    comparison = {
        "schemaVersion": "1.0", "assessmentId": job["assessmentId"], "jobId": job["jobId"], "workspaceId": job["workspaceId"],
        "datasetId": job["datasetId"], "deploymentId": job["deploymentId"],
        "assessmentPolicySha256": policy_hash, "candidateRegistrySha256": registry_hash, "rollingValidationSha256": rolling_hash,
        "foldPlanSha256": plan_hash, "plannedFoldCount": 68, "candidateSetStatus": candidate_set_status,
        "comparisonPolicy": {"policyId": policy["comparison_policy"]["policy_id"], "policyVersion": policy["comparison_policy"]["policy_version"],
            "primaryMetric": "mae", "tieSequence": policy["comparison_policy"]["tie_sequence"], "tieTolerance": 1e-9,
            "weightedScoring": False, "intersectionOnlyFolds": False},
        "candidates": candidate_results, "selectionEligibleCandidateIds": selection_ids,
        "technicalWinnerModelId": winner, "winnerParameterSha256": winner_candidate["parametersSha256"] if winner_candidate else None,
        "selectionReason": selection_reason, "tieStage": tie_stage, "tieResolutionSteps": tie_steps,
        "baselineRequirementSatisfied": baseline_ok, "learnedModelRequirementSatisfied": learned_ok,
        "automaticAdoptionAllowed": False, "generatedAt": _now(),
    }
    comparison_path = staging / "artifacts/candidate_model_comparison.json"
    atomic_json(comparison_path, comparison)
    comparison_hash = sha256_file(comparison_path)

    _update_job(job_path, job, progress="preparing_recommendation")
    recommendation_status = "evidence_only" if winner else "no_recommendation"
    limitations = [
        "This technical comparison applies only to the validated synthetic-benchmark-compatible uploaded dataset.",
        "Recommendation-strength thresholds are not governed; model adoption and approval controls remain disabled.",
        "No forecast, uncertainty calibration, preparedness output, or deployment-model change is produced by this assessment.",
    ]
    if winner in BASELINE_IDS:
        limitations.append("Baseline deployment is not governed. A baseline technical winner cannot be adopted in this phase.")
    winner_mae = winner_candidate["metrics"]["mae"] if winner_candidate else None
    runner_mae = runner_up["metrics"]["mae"] if runner_up else None
    recommendation = {
        "schemaVersion": "1.0", "assessmentId": job["assessmentId"], "jobId": job["jobId"], "workspaceId": job["workspaceId"],
        "datasetId": job["datasetId"], "deploymentId": job["deploymentId"], "assessmentPolicySha256": policy_hash,
        "comparisonSha256": comparison_hash, "foldPlanSha256": plan_hash, "candidateRegistrySha256": registry_hash,
        "recommendationPolicy": {"policyId": policy["recommendation_policy"]["policy_id"], "policyVersion": policy["recommendation_policy"]["policy_version"], "strengthThresholdStatus": "not_governed"},
        "technicalWinnerModelId": winner, "winnerParameterSha256": winner_candidate["parametersSha256"] if winner_candidate else None,
        "recommendationStatus": recommendation_status, "recommendationStrength": "not_available",
        "recommendationReason": selection_reason, "candidateSetStatus": candidate_set_status,
        "baselineRequirementSatisfied": baseline_ok, "learnedModelRequirementSatisfied": learned_ok,
        "evidenceInputs": {"winnerMae": winner_mae, "runnerUpMae": runner_mae,
            "absoluteMaeGap": (runner_mae - winner_mae) if winner_mae is not None and runner_mae is not None else None,
            "relativeMaeGap": ((runner_mae - winner_mae) / runner_mae) if winner_mae is not None and runner_mae not in {None, 0} else None,
            "successfulFoldRatio": 1.0 if winner else None, "failedFoldCount": winner_candidate["failedFolds"] if winner_candidate else 68,
            "clippingCount": winner_candidate["metrics"]["clippingCount"] if winner_candidate else 0,
            "warningCount": winner_candidate["metrics"]["warningCount"] if winner_candidate else 0,
            "candidateBreadth": len(complete), "tieBreakStageUsed": tie_stage, "datasetFoldCount": 68},
        "limitations": limitations, "approvalRequired": True, "approvalEnabled": False,
        "approvalStatus": "approval_pending", "adoptionStatus": "not_adopted", "automaticAdoptionAllowed": False,
        "generatedAt": _now(),
    }
    recommendation_path = staging / "artifacts/recommendation.json"
    atomic_json(recommendation_path, recommendation)
    recommendation_hash = sha256_file(recommendation_path)

    assessment = {
        "schemaVersion": "1.0", "assessmentId": job["assessmentId"], "jobId": job["jobId"], "workspaceId": job["workspaceId"],
        "datasetId": job["datasetId"], "deploymentId": job["deploymentId"], "sourceType": "uploaded",
        "acceptedPeriod": validation["acceptedPeriod"], "assessmentPolicy": {"policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_hash},
        "foldPlanSha256": plan_hash, "candidateRegistrySha256": registry_hash, "candidateSetStatus": candidate_set_status,
        "comparisonStatus": "complete", "recommendationStatus": recommendation_status, "approvalStatus": "approval_pending",
        "adoptionStatus": "not_adopted", "limitations": limitations,
        "provenance": {"validationRecordSha256": job["validationRecordSha256"],
            "canonicalDengueSha256": validation["files"]["canonical"]["dengueSha256"],
            "canonicalClimateSha256": validation["files"]["canonical"]["climateSha256"]},
        "artifactHashes": {"inputManifestSha256": sha256_file(staging / "artifacts/input_manifest.json"),
            "modelFeaturesSha256": sha256_file(feature_path), "rollingValidationSha256": rolling_hash,
            "candidateComparisonSha256": comparison_hash, "recommendationSha256": recommendation_hash,
            "assessmentSummarySha256": None},
        "artifactPublicationSequence": ["input_manifest.json", "model_features.csv", "rolling_validation.json", "candidate_model_comparison.json", "recommendation.json", "assessment_summary.json"],
        "generatedAt": _now(),
    }
    atomic_json(staging / "metadata/assessment.json", assessment)

    _update_job(job_path, job, progress="validating_evidence")
    for value, schema_name in ((rolling, SCHEMAS["rolling_validation.json"]), (comparison, SCHEMAS["candidate_model_comparison.json"]), (recommendation, SCHEMAS["recommendation.json"]), (assessment, SCHEMAS["assessment.json"])):
        _schema_validate(value, schema_name)
    committed_at = _now()
    summary = {
        "schemaVersion": "1.0", "assessmentId": job["assessmentId"], "jobId": job["jobId"], "workspaceId": job["workspaceId"],
        "datasetId": job["datasetId"], "deploymentId": job["deploymentId"], "sourceType": "uploaded", "acceptedPeriod": validation["acceptedPeriod"],
        "labelledRows": 173, "committedAt": committed_at, "assessmentStatus": "assessment_complete", "approvalStatus": "approval_pending",
        "adoptionStatus": "not_adopted", "foldPolicy": {"policyId": policy["fold_policy"]["policy_id"], "policyVersion": policy["fold_policy"]["policy_version"],
            "plannedFoldCount": 68, "initialTrainingRows": 104, "embargoRows": 1, "validationRowsPerFold": 1,
            "stepSizeWeeks": 1, "horizonWeeks": 2, "samePlanForAllCandidates": True},
        "foldPlanSha256": plan_hash, "candidateSetStatus": candidate_set_status, "candidates": candidate_results,
        "technicalWinnerModelId": winner, "selectionReason": selection_reason, "tieStage": tie_stage,
        "baselineRequirementSatisfied": baseline_ok, "learnedModelRequirementSatisfied": learned_ok,
        "recommendationStatus": recommendation_status, "recommendationStrength": "not_available",
        "approvalRequired": True, "approvalEnabled": False, "limitations": limitations,
        "evidenceHashes": {"rollingValidationSha256": rolling_hash, "candidateComparisonSha256": comparison_hash, "recommendationSha256": recommendation_hash},
        "provenance": {"validationRecordSha256": job["validationRecordSha256"], "assessmentPolicySha256": policy_hash,
            "candidateRegistrySha256": registry_hash, "featureOrderSha256": feature_hash},
    }
    _schema_validate(summary, SCHEMAS["assessment_summary.json"])
    atomic_json(staging / "artifacts/assessment_summary.json", summary)
    assessment["artifactHashes"]["assessmentSummarySha256"] = sha256_file(staging / "artifacts/assessment_summary.json")
    atomic_json(staging / "metadata/assessment.json", assessment)
    _schema_validate(assessment, SCHEMAS["assessment.json"])
    logs = staging / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "events.jsonl").write_text(json.dumps({"timestamp": _now(), "eventType": "assessment_evidence_ready", "assessmentId": job["assessmentId"]}) + "\n", encoding="utf-8")
    _update_job(job_path, job, status="committing", progress="committing_assessment")
    committed = commit_runtime_assessment(runtime_root, staging, job)
    return {"assessmentId": job["assessmentId"], "technicalWinnerModelId": winner, "foldPlanSha256": plan_hash, "committed": True, "commit": committed["commit"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--job-record", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--staging", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args), separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "code": "runtime_assessment_failed", "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
