"""Validate and atomically commit isolated P1.4D-2 assessment evidence."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within


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
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
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


def _reconcile(rolling: dict[str, Any], comparison: dict[str, Any], recommendation: dict[str, Any]) -> None:
    folds = rolling["folds"]
    candidate_ids = rolling["candidateIds"]
    if rolling["plannedFoldCount"] != 68 or len(folds) != 68 or len(candidate_ids) != 7:
        raise RuntimeAssessmentCommitError("Assessment must contain the governed 68-fold, seven-candidate plan.")
    if len({fold["foldId"] for fold in folds}) != 68:
        raise RuntimeAssessmentCommitError("Assessment fold identities are not unique.")
    records: dict[str, list[dict[str, Any]]] = {model_id: [] for model_id in candidate_ids}
    for sequence, fold in enumerate(folds, 1):
        if fold["sequence"] != sequence:
            raise RuntimeAssessmentCommitError("Assessment fold sequence is not deterministic.")
        predictions = fold["predictions"]
        if len(predictions) != 7 or {item["modelId"] for item in predictions} != set(candidate_ids):
            raise RuntimeAssessmentCommitError("Every assessment fold must contain every governed candidate exactly once.")
        for item in predictions:
            records[item["modelId"]].append(item)
    summaries = {item["modelId"]: item for item in comparison["candidates"]}
    if set(summaries) != set(candidate_ids):
        raise RuntimeAssessmentCommitError("Candidate comparison does not reconcile with the fold plan.")
    for model_id, candidate_records in records.items():
        successful = sum(item["foldStatus"] in {"success", "warning"} for item in candidate_records)
        failed = len(candidate_records) - successful
        summary = summaries[model_id]
        if (summary["successfulFolds"], summary["failedFolds"]) != (successful, failed):
            raise RuntimeAssessmentCommitError(f"Candidate fold totals do not reconcile: {model_id}.")
        if summary["selectionEligible"] and (not summary["eligible"] or successful != 68 or failed != 0):
            raise RuntimeAssessmentCommitError(f"Incomplete candidate is selection eligible: {model_id}.")
    winner = comparison["technicalWinnerModelId"]
    if winner is not None and not summaries[winner]["selectionEligible"]:
        raise RuntimeAssessmentCommitError("Technical winner is not selection eligible.")
    if recommendation["technicalWinnerModelId"] != winner:
        raise RuntimeAssessmentCommitError("Recommendation winner differs from comparison evidence.")
    expected_status = "evidence_only" if winner else "no_recommendation"
    if recommendation["recommendationStatus"] != expected_status:
        raise RuntimeAssessmentCommitError("Recommendation status does not match technical evidence.")
    if recommendation["recommendationStrength"] != "not_available" or recommendation["approvalEnabled"] is not False:
        raise RuntimeAssessmentCommitError("Recommendation strength or approval exceeded the governed phase.")
    if recommendation["adoptionStatus"] != "not_adopted":
        raise RuntimeAssessmentCommitError("Assessment evidence cannot adopt a model.")


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
    _reconcile(rolling, comparison, recommendation)
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
