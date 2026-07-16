"""Validate and atomically commit isolated P1.4D-2 assessment evidence."""
from __future__ import annotations

import csv
import json
import math
import os
import stat
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from feature_engineering import FEATURE_COLUMNS
from runtime_assessment_evidence import (
    AssessmentEvidenceError,
    aggregate_candidate,
    fold_plan_sha256,
    selection_eligible,
    select_technical_winner,
    validate_fold_identities,
    validate_folds_against_feature_rows,
    validate_prediction_record,
)
from runtime_validate import TARGET


SCHEMAS = {
    "metadata/assessment.json": "runtime_assessment.schema.json",
    "artifacts/rolling_validation.json": "runtime_rolling_validation.schema.json",
    "artifacts/candidate_model_comparison.json": "runtime_candidate_comparison.schema.json",
    "artifacts/recommendation.json": "runtime_recommendation.schema.json",
    "artifacts/assessment_summary.json": "runtime_assessment_summary.schema.json",
}
REQUIRED_ARTIFACTS = {
    "input_manifest.json", "model_features.csv", "rolling_validation.json",
    "candidate_model_comparison.json", "recommendation.json", "assessment_summary.json",
}
PROHIBITED_ARTIFACTS = {
    "forecast_output.json", "forecast_uncertainty.json", "model_card.json",
    "dashboard_summary.json", "directives.json", "planning_scenarios.json",
    "preparedness.json", "facility_projections.json", "inventory_alerts.json", "alerts.json",
}


class RuntimeAssessmentCommitError(RuntimeError):
    """Raised when assessment evidence cannot be committed safely."""


def _json(path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ValueError(f"Non-standard JSON numeric constant: {value}.")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeAssessmentCommitError(f"Invalid assessment JSON: {path.name}.") from exc
    if not isinstance(value, dict):
        raise RuntimeAssessmentCommitError(f"Assessment JSON must be an object: {path.name}.")
    return value


def _validate(path: Path, schema_name: str) -> dict[str, Any]:
    value = _json(path)
    schema = _json(ROOT / "config" / schema_name)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors:
        raise RuntimeAssessmentCommitError(f"{path.name} failed its runtime schema: {errors[0].message}")
    return value


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
        for path in root.rglob("*"):
            if path.is_file():
                path.chmod(stat.S_IREAD)
        return
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _same_metrics(actual: dict[str, Any] | None, expected: dict[str, Any] | None) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if set(actual) != set(expected):
        return False
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, float):
            if not isinstance(actual_value, (int, float)) or not math.isfinite(float(actual_value)):
                return False
            if float(actual_value) != expected_value:
                return False
        elif actual_value != expected_value:
            return False
    return True


def _reconcile(
    rolling: dict[str, Any], comparison: dict[str, Any], recommendation: dict[str, Any],
    feature_rows: list[dict[str, str]],
) -> None:
    folds = rolling["folds"]
    candidate_ids = rolling["candidateIds"]
    if rolling["plannedFoldCount"] != 68:
        raise RuntimeAssessmentCommitError("Assessment must contain the governed 68-fold plan.")
    try:
        actuals, records = validate_fold_identities(folds, candidate_ids)
        validate_folds_against_feature_rows(folds, feature_rows, FEATURE_COLUMNS, TARGET)
    except AssessmentEvidenceError as exc:
        raise RuntimeAssessmentCommitError(f"Assessment fold evidence is invalid: {exc}.") from exc
    computed_fold_hash = fold_plan_sha256(folds)
    if computed_fold_hash != rolling["foldPlanSha256"] or computed_fold_hash != comparison["foldPlanSha256"] \
            or computed_fold_hash != recommendation["foldPlanSha256"]:
        raise RuntimeAssessmentCommitError("Assessment fold-plan SHA-256 does not match canonical fold evidence.")
    summaries = {item["modelId"]: item for item in comparison["candidates"]}
    if set(summaries) != set(candidate_ids):
        raise RuntimeAssessmentCommitError("Candidate comparison does not reconcile with the fold plan.")
    recomputed: list[dict[str, Any]] = []
    for model_id, candidate_records in records.items():
        try:
            for actual, record in zip(actuals, candidate_records):
                validate_prediction_record(model_id, actual, record)
        except (AssessmentEvidenceError, TypeError, ValueError, KeyError) as exc:
            raise RuntimeAssessmentCommitError(f"Candidate fold evidence is invalid: {model_id}: {exc}.") from exc
        successful = sum(item["foldStatus"] in {"success", "warning"} for item in candidate_records)
        failed = len(candidate_records) - successful
        summary = summaries[model_id]
        if (summary["successfulFolds"], summary["failedFolds"]) != (successful, failed):
            raise RuntimeAssessmentCommitError(f"Candidate fold totals do not reconcile: {model_id}.")
        if summary["eligible"] is not True:
            raise RuntimeAssessmentCommitError(f"Governed full-assessment candidate was marked preflight-ineligible: {model_id}.")
        try:
            metrics = aggregate_candidate(candidate_records, actuals)
        except AssessmentEvidenceError as exc:
            raise RuntimeAssessmentCommitError(f"Candidate aggregate is invalid: {model_id}: {exc}.") from exc
        if not _same_metrics(summary["metrics"], metrics):
            raise RuntimeAssessmentCommitError(f"Candidate aggregate metrics do not reconcile: {model_id}.")
        eligible = selection_eligible(
            policy_eligible=True, successful_folds=successful, failed_folds=failed, metrics=metrics,
        )
        if summary["selectionEligible"] is not eligible:
            raise RuntimeAssessmentCommitError(f"Candidate selection eligibility does not reconcile: {model_id}.")
        expected_completion = "complete" if successful == 68 and failed == 0 else "incomplete"
        if summary["completionStatus"] != expected_completion:
            raise RuntimeAssessmentCommitError(f"Candidate completion status does not reconcile: {model_id}.")
        recomputed.append({**summary, "metrics": metrics, "selectionEligible": eligible})

    complete = [candidate for candidate in recomputed if candidate["selectionEligible"]]
    baseline_ids = {"previous_week_naive", "moving_average_4w", "seasonal_naive_52w"}
    learned_ids = {"ridge_regression", "poisson_regression", "random_forest", "gradient_boosting"}
    baseline_ok = any(candidate["modelId"] in baseline_ids for candidate in complete)
    learned_ok = any(candidate["modelId"] in learned_ids for candidate in complete)
    expected_set_status = (
        "insufficient_candidate_breadth" if len(complete) < 2 or not baseline_ok or not learned_ok
        else "complete_candidate_set" if len(complete) == 7
        else "partial_candidate_set"
    )
    if comparison["candidateSetStatus"] != expected_set_status \
            or comparison["baselineRequirementSatisfied"] is not baseline_ok \
            or comparison["learnedModelRequirementSatisfied"] is not learned_ok:
        raise RuntimeAssessmentCommitError("Candidate-set eligibility gates do not reconcile.")
    winner, tie_stage, tie_steps, eligible_ids = (
        select_technical_winner(recomputed) if baseline_ok and learned_ok else (None, None, [], [])
    )
    if comparison["selectionEligibleCandidateIds"] != eligible_ids \
            or comparison["technicalWinnerModelId"] != winner \
            or comparison["tieStage"] != tie_stage \
            or comparison["tieResolutionSteps"] != tie_steps:
        raise RuntimeAssessmentCommitError("Technical-winner selection does not reconcile with candidate evidence.")
    if winner is not None and not summaries[winner]["selectionEligible"]:
        raise RuntimeAssessmentCommitError("Technical winner is not selection eligible.")
    winner_candidate = summaries.get(winner) if winner else None
    if comparison["winnerParameterSha256"] != (winner_candidate["parametersSha256"] if winner_candidate else None):
        raise RuntimeAssessmentCommitError("Winner parameter identity does not reconcile.")

    winner_records = records.get(winner, []) if winner else []
    for candidate in recomputed:
        expected_counts = None
        if winner:
            better = tied = worse = 0
            for record, selected in zip(records[candidate["modelId"]], winner_records):
                if record["absoluteError"] is None or selected["absoluteError"] is None:
                    continue
                difference = float(record["absoluteError"]) - float(selected["absoluteError"])
                better += difference < -1e-9
                tied += abs(difference) <= 1e-9
                worse += difference > 1e-9
            expected_counts = {"better": better, "tied": tied, "worse": worse}
        if candidate["foldWinsTiesLosses"] != expected_counts:
            raise RuntimeAssessmentCommitError(f"Fold wins/ties/losses do not reconcile: {candidate['modelId']}.")

    if recommendation["technicalWinnerModelId"] != winner:
        raise RuntimeAssessmentCommitError("Recommendation winner differs from comparison evidence.")
    expected_status = "evidence_only" if winner else "no_recommendation"
    if recommendation["recommendationStatus"] != expected_status:
        raise RuntimeAssessmentCommitError("Recommendation status does not match technical evidence.")
    if recommendation["recommendationStrength"] != "not_available" or recommendation["approvalEnabled"] is not False:
        raise RuntimeAssessmentCommitError("Recommendation strength or approval exceeded the governed phase.")
    if recommendation["adoptionStatus"] != "not_adopted":
        raise RuntimeAssessmentCommitError("Assessment evidence cannot adopt a model.")
    if recommendation["winnerParameterSha256"] != (winner_candidate["parametersSha256"] if winner_candidate else None):
        raise RuntimeAssessmentCommitError("Recommendation winner parameters do not reconcile.")
    runner_up = min(
        (candidate for candidate in complete if candidate["modelId"] != winner),
        key=lambda candidate: candidate["metrics"]["mae"],
        default=None,
    ) if winner else None
    winner_mae = winner_candidate["metrics"]["mae"] if winner_candidate else None
    runner_mae = runner_up["metrics"]["mae"] if runner_up else None
    expected_inputs = {
        "winnerMae": winner_mae,
        "runnerUpMae": runner_mae,
        "absoluteMaeGap": (runner_mae - winner_mae) if winner_mae is not None and runner_mae is not None else None,
        "relativeMaeGap": ((runner_mae - winner_mae) / runner_mae) if winner_mae is not None and runner_mae not in {None, 0} else None,
        "successfulFoldRatio": 1.0 if winner else None,
        "failedFoldCount": winner_candidate["failedFolds"] if winner_candidate else 68,
        "clippingCount": winner_candidate["metrics"]["clippingCount"] if winner_candidate else 0,
        "warningCount": winner_candidate["metrics"]["warningCount"] if winner_candidate else 0,
        "candidateBreadth": len(complete),
        "tieBreakStageUsed": tie_stage,
        "datasetFoldCount": 68,
    }
    if recommendation["evidenceInputs"] != expected_inputs:
        raise RuntimeAssessmentCommitError("Recommendation evidence inputs do not reconcile with candidate metrics.")


def commit_runtime_assessment(runtime_root: Path, staging_path: Path, job: dict[str, Any]) -> dict[str, Any]:
    runtime_root = require_absolute_directory(runtime_root, "runtime root")
    staging = require_within(runtime_root, staging_path, "assessment staging")
    if staging.parent != (runtime_root / "assessment-staging").resolve() or staging.name != job.get("assessmentId"):
        raise RuntimeAssessmentCommitError("Assessment staging identity does not match the job.")
    artifacts = staging / "artifacts"
    metadata = staging / "metadata"
    present = {path.name for path in artifacts.iterdir()} if artifacts.exists() else set()
    missing = REQUIRED_ARTIFACTS - present
    prohibited = PROHIBITED_ARTIFACTS & present
    if missing:
        raise RuntimeAssessmentCommitError(f"Assessment evidence is incomplete: {sorted(missing)}")
    if prohibited:
        raise RuntimeAssessmentCommitError(f"Prohibited assessment artifacts are present: {sorted(prohibited)}")

    values = {relative: _validate(staging / relative, schema) for relative, schema in SCHEMAS.items()}
    assessment = values["metadata/assessment.json"]
    rolling = values["artifacts/rolling_validation.json"]
    comparison = values["artifacts/candidate_model_comparison.json"]
    recommendation = values["artifacts/recommendation.json"]
    summary = values["artifacts/assessment_summary.json"]
    identity = (job["assessmentId"], job["jobId"], job["datasetId"], job["deploymentId"])
    for value in (assessment, rolling, comparison, recommendation, summary):
        if tuple(value.get(key) for key in ("assessmentId", "jobId", "datasetId", "deploymentId")) != identity:
            raise RuntimeAssessmentCommitError("Assessment artifact identity mismatch.")
    if rolling["foldPlanSha256"] != assessment["foldPlanSha256"] or comparison["foldPlanSha256"] != assessment["foldPlanSha256"]:
        raise RuntimeAssessmentCommitError("Assessment fold-plan identity mismatch.")
    if summary["candidates"] != comparison["candidates"] or summary["technicalWinnerModelId"] != comparison["technicalWinnerModelId"]:
        raise RuntimeAssessmentCommitError("Compact assessment summary differs from comparison evidence.")
    try:
        with (artifacts / "model_features.csv").open("r", encoding="utf-8", newline="") as handle:
            feature_rows = list(csv.DictReader(handle))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise RuntimeAssessmentCommitError("Assessment feature matrix is not valid canonical CSV.") from exc
    _reconcile(rolling, comparison, recommendation, feature_rows)
    sequence = assessment.get("artifactPublicationSequence", [])
    if not sequence or sequence[-1] != "assessment_summary.json":
        raise RuntimeAssessmentCommitError("Assessment summary was not published last among evidence artifacts.")

    hashes = {name: sha256_file(artifacts / name) for name in sorted(REQUIRED_ARTIFACTS)}
    expected = assessment["artifactHashes"]
    for name, field in (
        ("input_manifest.json", "inputManifestSha256"), ("model_features.csv", "modelFeaturesSha256"),
        ("rolling_validation.json", "rollingValidationSha256"),
        ("candidate_model_comparison.json", "candidateComparisonSha256"),
        ("recommendation.json", "recommendationSha256"),
        ("assessment_summary.json", "assessmentSummarySha256"),
    ):
        if expected.get(field) != hashes[name]:
            raise RuntimeAssessmentCommitError(f"Assessment artifact hash mismatch: {name}.")
    if summary["evidenceHashes"]["rollingValidationSha256"] != hashes["rolling_validation.json"] \
            or summary["evidenceHashes"]["candidateComparisonSha256"] != hashes["candidate_model_comparison.json"] \
            or summary["evidenceHashes"]["recommendationSha256"] != hashes["recommendation.json"]:
        raise RuntimeAssessmentCommitError("Assessment summary evidence hashes do not reconcile.")

    commit = {
        "schemaVersion": "1.0", "assessmentId": job["assessmentId"], "jobId": job["jobId"],
        "workspaceId": job["workspaceId"], "datasetId": job["datasetId"], "deploymentId": job["deploymentId"],
        "workflowMode": "assess_dataset", "sourceType": "uploaded", "status": "committed",
        "validationRecordSha256": job["validationRecordSha256"],
        "assessmentPolicySha256": job["assessmentPolicySha256"],
        "candidateRegistrySha256": job["candidateRegistrySha256"], "foldPlanSha256": assessment["foldPlanSha256"],
        "artifactHashes": hashes, "summaryPublishedLast": True, "prohibitedArtifactsAbsent": True,
        "latestPointerUpdated": False, "committedAt": summary["committedAt"],
    }
    schema = _json(ROOT / "config" / "runtime_assessment_commit.schema.json")
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(commit)
    atomic_json(metadata / "commit.json", commit)

    assessments = (runtime_root / "assessments").resolve()
    assessments.mkdir(parents=True, exist_ok=True)
    committed = assessments / job["assessmentId"]
    if committed.exists():
        raise RuntimeAssessmentCommitError("The immutable assessment already exists.")
    os.replace(staging, committed)
    _fsync_directory(assessments)
    _make_immutable(committed)
    return {"assessmentRoot": str(committed), "commit": commit}
