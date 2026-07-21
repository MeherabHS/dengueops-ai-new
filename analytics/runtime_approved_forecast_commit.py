"""Validate and atomically commit one decision-authorized forecast run."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from runtime_assessment_policy import load_and_validate_assessment_policy
from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_uncertainty import validate_uncertainty_contract, UncertaintyContractError


P1_ASSESSMENT_SHA = "dbf9d4cc4713bbb9d114b2dab916d0f20b3004ac14b37ca663c3caecefcea0af"
P2_ASSESSMENT_SHA = "04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff"
P2_V2_ASSESSMENT_SHA = "569faeca27a4715e72085ac97c78b00f83351bd7783fc156f5bd8f626cab28b8"
P1_DECISION_SHA = "8fece340b85951d3bee8b037c4ac79ae82636ee371a934e9371bcb4a633491a4"
P2_DECISION_SHA = "aaef2ed2afd3afe03a0aec91889f144a3274cad21aa8cef8ef772bb90cfdcb4a"
P2_V2_DECISION_SHA = "6f643f01e7e01353986af52f395b2c71cb05dc162ba7f71127c1397ce2adcf1d"
ASSESSMENT_POLICY_ID = "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE"
DECISION_POLICY_ID = "RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION"

SCHEMAS = {
    "metadata/run.json": "runtime_approved_forecast_run.schema.json",
    "artifacts/forecast_output.json": "runtime_approved_forecast_output.schema.json",
    "artifacts/forecast_uncertainty.json": "runtime_approved_forecast_uncertainty.schema.json",
    "artifacts/dashboard_summary.json": "runtime_approved_forecast_dashboard.schema.json",
    "artifacts/model_card.json": "runtime_approved_forecast_model_card.schema.json",
}
REQUIRED = {"input_manifest.json", "model_features.csv", "forecast_output.json", "forecast_uncertainty.json",
            "model_card.json", "dashboard_summary.json", "chart_data.json", "pipeline_run_summary.json"}
PROHIBITED = {"candidate_model_comparison.json", "rolling_validation.json", "recommendation.json", "directives.json",
              "preparedness.json", "planning_scenarios.json", "facility_projections.json", "inventory_alerts.json",
              "alerts.json"}


class ApprovedForecastCommitError(RuntimeError):
    pass


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ApprovedForecastCommitError(f"Invalid approved forecast JSON: {path.name}.") from exc
    if not isinstance(value, dict):
        raise ApprovedForecastCommitError(f"Approved forecast JSON must be an object: {path.name}.")
    return value


def _validate(path: Path, schema: str) -> dict[str, Any]:
    value, definition = _json(path), _json(ROOT / "config" / schema)
    errors = sorted(Draft202012Validator(definition, format_checker=FormatChecker()).iter_errors(value),
                    key=lambda error: list(error.path))
    if errors:
        raise ApprovedForecastCommitError(f"{path.name} failed schema validation: {errors[0].message}")
    return value


def _lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 30
    while True:
        try:
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if time.monotonic() > deadline:
                raise ApprovedForecastCommitError("Deployment commit lock timed out.")
            time.sleep(.1)


def _fsync(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _immutable(root: Path) -> None:
    if os.name == "nt":
        return
    for path in sorted(root.rglob("*"), reverse=True):
        path.chmod(0o555 if path.is_dir() else 0o444)
    root.chmod(0o555)


def _canonical_policy_sha256(policy: dict[str, Any]) -> str:
    content = dict(policy)
    content.pop("policySha256", None)
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verify_policy(decision: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    identity = (decision.get("schemaVersion"), decision.get("assessmentPolicyId"),
                decision.get("assessmentPolicyVersion"), decision.get("assessmentPolicySha256"),
                decision.get("decisionPolicyId"), decision.get("decisionPolicyVersion"),
                decision.get("decisionPolicySha256"))
    p1 = ("1.0", ASSESSMENT_POLICY_ID, "p1.4d-1-v1", P1_ASSESSMENT_SHA,
          DECISION_POLICY_ID, "p1.4d-3-e-v1", P1_DECISION_SHA)
    p2 = ("2.0", ASSESSMENT_POLICY_ID, "p2-v1", P2_ASSESSMENT_SHA,
          DECISION_POLICY_ID, "p2-v1", P2_DECISION_SHA)
    p2v2 = ("2.0", ASSESSMENT_POLICY_ID, "p2-v2", P2_V2_ASSESSMENT_SHA,
            DECISION_POLICY_ID, "p2-v2", P2_V2_DECISION_SHA)
    if identity == p1:
        filename, phase_two = "decision_policy_p1.4d-3-e-v1.json", False
    elif identity == p2:
        filename, phase_two = "decision_policy_p2-v1.json", True
    elif identity == p2v2:
        filename, phase_two = "decision_policy.json", True
    else:
        raise ApprovedForecastCommitError("The approved forecast has an unsupported or hybrid policy identity.")
    policy = _json(ROOT / "config/deployments/dhaka_south" / filename)
    errors = list(Draft202012Validator(_json(ROOT / "config/runtime_decision_policy.schema.json"),
                                       format_checker=FormatChecker()).iter_errors(policy))
    if errors or policy.get("policySha256") != _canonical_policy_sha256(policy) or identity[4:] != (
            policy.get("policyId"), policy.get("policyVersion"), policy.get("policySha256")):
        raise ApprovedForecastCommitError("The decision policy failed independent validation.")
    try:
        load_and_validate_assessment_policy("dhaka_south", identity[2], identity[3])
    except Exception as exc:
        raise ApprovedForecastCommitError("The assessment policy failed independent validation.") from exc
    return policy, phase_two


def _same(left: Any, right: Any, message: str) -> None:
    if left != right:
        raise ApprovedForecastCommitError(message)


def _verify_phase_two(root: Path, staging: Path, job: dict[str, Any], run: dict[str, Any],
                      forecast: dict[str, Any], uncertainty: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    decision_root = require_within(root, root / "decisions" / job["decisionId"], "decision")
    decision_path, decision_commit_path = decision_root / "decision.json", decision_root / "commit.json"
    decision, decision_commit = _json(decision_path), _json(decision_commit_path)
    _same(sha256_file(decision_commit_path), job["decisionCommitSha256"], "Decision commit binding changed.")
    _same(decision_commit.get("decisionSha256"), sha256_file(decision_path), "Decision artifact hash changed.")
    policy, phase_two = _verify_policy(decision)
    if not phase_two:
        raise ApprovedForecastCommitError("A schema 2.0 run cannot use Phase 1 evidence.")

    assessment_root = require_within(root, root / "assessments" / job["assessmentId"], "assessment")
    assessment_commit_path = assessment_root / "metadata/commit.json"
    assessment_commit = _json(assessment_commit_path)
    _same(sha256_file(assessment_commit_path), job["assessmentCommitSha256"], "Assessment commit binding changed.")
    artifacts: dict[str, dict[str, Any]] = {}
    for name in ("assessment_summary.json", "candidate_model_comparison.json", "rolling_validation.json"):
        path = assessment_root / "artifacts" / name
        _same(assessment_commit.get("artifactHashes", {}).get(name), sha256_file(path), f"Assessment artifact changed: {name}.")
        artifacts[name] = _json(path)
    summary = artifacts["assessment_summary.json"]
    comparison = artifacts["candidate_model_comparison.json"]
    rolling = artifacts["rolling_validation.json"]

    auth_root = require_within(root, root / "authorizations" / job["authorizationId"], "authorization")
    authorization_path, authorization_commit_path = auth_root / "authorization.json", auth_root / "commit.json"
    authorization, authorization_commit = _json(authorization_path), _json(authorization_commit_path)
    authorization_commit_sha = sha256_file(authorization_commit_path)
    _same(authorization_commit.get("authorizationSha256"), sha256_file(authorization_path), "Authorization file hash changed.")
    _same(authorization_commit.get("decisionCommitSha256"), job["decisionCommitSha256"], "Authorization decision binding changed.")
    _same(authorization.get("initialStatus"), "available", "Authorization initial status changed.")
    _same(authorization.get("scope"), "one_run", "Authorization scope changed.")
    if datetime.fromisoformat(authorization["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise ApprovedForecastCommitError("The authorization expired before commit.")

    selected = next((value for value in summary.get("candidates", []) if value.get("modelId") == job["selectedModelId"]), None)
    compared = next((value for value in comparison.get("candidates", []) if value.get("modelId") == job["selectedModelId"]), None)
    winner = next((value for value in summary.get("candidates", []) if value.get("modelId") == summary.get("technicalWinnerModelId")), None)
    if not selected or not compared:
        raise ApprovedForecastCommitError("Selected-model assessment evidence is absent.")
    labelled_rows = summary.get("labelledRows")
    planned_folds = summary.get("foldPolicy", {}).get("plannedFoldCount")
    evaluation_period = summary.get("foldPolicy", {}).get("selectedEvaluationPeriod")
    decision_v2 = decision.get("decisionPolicyVersion") == "p2-v2"
    assessment_version = "p2-v2" if decision_v2 else "p2-v1"
    assessment_sha = P2_V2_ASSESSMENT_SHA if decision_v2 else P2_ASSESSMENT_SHA
    assessment_policy = {"policyId": ASSESSMENT_POLICY_ID, "policyVersion": assessment_version, "policySha256": assessment_sha}
    decision_policy = {"policyId": DECISION_POLICY_ID, "policyVersion": decision.get("decisionPolicyVersion"), "policySha256": policy["policySha256"]}

    checks = (
        (assessment_commit.get("assessmentPolicyId"), ASSESSMENT_POLICY_ID, "Assessment policy ID changed."),
        (assessment_commit.get("assessmentPolicyVersion"), assessment_version, "Assessment policy version changed."),
        (assessment_commit.get("assessmentPolicySha256"), assessment_sha, "Assessment policy hash changed."),
        (assessment_commit.get("candidateRegistrySha256"), policy["candidateRegistrySha256"], "Candidate registry hash changed."),
        (rolling.get("assessmentPolicy"), assessment_policy, "Rolling assessment policy changed."),
        (comparison.get("candidateRegistrySha256"), policy["candidateRegistrySha256"], "Comparison registry hash changed."),
        (rolling.get("candidateRegistrySha256"), policy["candidateRegistrySha256"], "Rolling registry hash changed."),
        (comparison.get("technicalWinnerModelId"), summary.get("technicalWinnerModelId"), "Technical winner changed."),
        (decision.get("technicalWinnerModelId"), summary.get("technicalWinnerModelId"), "Decision technical winner changed."),
        (decision.get("technicalWinnerParameterSha256"), (winner or {}).get("parametersSha256"), "Winner parameter hash changed."),
        (selected.get("parametersSha256"), job["selectedModelParameterSha256"], "Selected parameter hash changed."),
        (compared.get("parametersSha256"), job["selectedModelParameterSha256"], "Comparison parameter hash changed."),
        (selected.get("successfulFolds"), planned_folds, "Successful-fold count changed."),
        (compared.get("successfulFolds"), planned_folds, "Comparison successful-fold count changed."),
        (selected.get("failedFolds"), 0, "Selected candidate has failed folds."),
        (compared.get("failedFolds"), 0, "Comparison selected candidate has failed folds."),
        (comparison.get("plannedFoldCount"), planned_folds, "Comparison planned-fold count changed."),
        (rolling.get("plannedFoldCount"), planned_folds, "Rolling planned-fold count changed."),
        (len(rolling.get("folds", [])), planned_folds, "Rolling fold evidence is incomplete."),
        (comparison.get("labelledRows"), labelled_rows, "Comparison labelled rows changed."),
        (rolling.get("labelledRows"), labelled_rows, "Rolling labelled rows changed."),
        (comparison.get("selectedEvaluationPeriod"), evaluation_period, "Comparison period changed."),
        (rolling.get("selectedEvaluationPeriod"), evaluation_period, "Rolling period changed."),
        (comparison.get("foldPlanSha256"), summary.get("foldPlanSha256"), "Comparison fold plan changed."),
        (rolling.get("foldPlanSha256"), summary.get("foldPlanSha256"), "Rolling fold plan changed."),
    )
    for actual, expected, message in checks:
        _same(actual, expected, message)
    if decision_v2:
        for actual, expected, message in (
            (selected.get("candidateClass"), "learned_model", "Selected candidate class changed."),
            (selected.get("status"), decision.get("selectedCandidateStatus"), "Selected candidate status changed."),
            (selected.get("modelFamily"), decision.get("selectedModelFamily"), "Selected model family changed."),
            (selected.get("preprocessingIdentity"), decision.get("selectedModelPreprocessingIdentity"), "Selected preprocessing identity changed."),
            (selected.get("foldPlanSha256"), summary.get("foldPlanSha256"), "Selected fold plan changed."),
            (decision.get("featureOrderSha256"), summary.get("provenance", {}).get("featureOrderSha256"), "Decision feature order changed."),
            (decision.get("deploymentModelAdopted"), False, "One-run decision adopted a deployment model."),
        ):
            _same(actual, expected, message)
    if not isinstance(labelled_rows, int) or labelled_rows < 157 or not isinstance(planned_folds, int) or not 52 <= planned_folds <= 68:
        raise ApprovedForecastCommitError("Dynamic assessment history is invalid.")

    for key in ("assessmentId", "assessmentCommitSha256", "selectedModelId", "selectedModelParameterSha256",
                "assessmentPolicyId", "assessmentPolicyVersion", "assessmentPolicySha256", "decisionPolicyId",
                "decisionPolicyVersion", "decisionPolicySha256", "assessmentLabelledRows",
                "assessmentPlannedFoldCount", "foldPlanSha256"):
        _same(authorization.get(key), decision.get(key), f"Authorization evidence changed: {key}.")
    _same(authorization_commit_sha, run["authorizationCommitSha256"], "Run authorization commit hash changed.")

    governance = forecast["governanceEvidence"]
    expected_governance = {"assessmentCommitSha256": job["assessmentCommitSha256"],
                           "decisionCommitSha256": job["decisionCommitSha256"],
                           "authorizationCommitSha256": authorization_commit_sha,
                           "assessmentPolicy": assessment_policy, "decisionPolicy": decision_policy,
                           "candidateRegistrySha256": policy["candidateRegistrySha256"],
                           "assessmentLabelledRows": labelled_rows, "assessmentPlannedFoldCount": planned_folds,
                           "successfulFolds": planned_folds, "failedFolds": 0,
                           "selectedEvaluationPeriod": evaluation_period, "foldPlanSha256": summary["foldPlanSha256"]}
    if decision_v2:
        expected_governance.update({"selectedModelFamily": decision["selectedModelFamily"],
                                    "selectedModelPreprocessingIdentity": decision["selectedModelPreprocessingIdentity"],
                                    "featureOrderSha256": decision["featureOrderSha256"],
                                    "selectionType": decision["selectionType"]})
    _same(governance, expected_governance, "Forecast governance evidence does not reconcile.")

    training = forecast["trainingDataIdentity"]
    matrix_path = staging / "artifacts/model_features.csv"
    matrix_sha = sha256_file(matrix_path)
    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != labelled_rows:
        raise ApprovedForecastCommitError("Rebuilt training-row count does not match assessment evidence.")
    rebuilt_period = {"start": f"{int(rows[0]['epi_year'])}-W{int(rows[0]['epi_week']):02d}",
                      "end": f"{int(rows[-1]['epi_year'])}-W{int(rows[-1]['epi_week']):02d}"}
    _same(training.get("trainingRowCount"), labelled_rows, "Forecast training-row evidence changed.")
    _same(training.get("trainingPeriod"), rebuilt_period, "Forecast training period changed.")
    _same(training.get("featureMatrixSha256"), matrix_sha, "Forecast feature matrix hash changed.")
    _same(training.get("featureOrderSha256"), summary["provenance"]["featureOrderSha256"], "Feature-order hash changed.")

    run_checks = {"decisionCommitSha256": job["decisionCommitSha256"], "assessmentCommitSha256": job["assessmentCommitSha256"],
                  "authorizationCommitSha256": authorization_commit_sha, "assessmentPolicy": assessment_policy,
                  "decisionPolicy": decision_policy, "candidateRegistrySha256": policy["candidateRegistrySha256"],
                  "assessmentLabelledRows": labelled_rows, "assessmentPlannedFoldCount": planned_folds,
                  "selectedEvaluationPeriod": evaluation_period, "foldPlanSha256": summary["foldPlanSha256"],
                  "trainingRowCount": labelled_rows, "trainingPeriod": rebuilt_period,
                  "featureMatrixSha256": matrix_sha, "featureOrderSha256": summary["provenance"]["featureOrderSha256"]}
    for key, expected in run_checks.items():
        _same(run.get(key), expected, f"Run evidence changed: {key}.")
    _same(card.get("training"), training, "Model-card training evidence changed.")
    _same(card.get("features", {}).get("matrixSha256"), matrix_sha, "Model-card feature matrix changed.")
    _same(card.get("assessment", {}).get("selectedEvaluationPeriod"), evaluation_period, "Model-card assessment period changed.")
    _same(card.get("authorization", {}).get("status"), "reserved", "Model-card authorization status changed.")
    _same(forecast.get("horizonWeeks"), 2, "Forecast horizon changed.")
    _same(forecast.get("target"), "target_cases_next_2w", "Forecast target changed.")
    if decision_v2:
        try:
            validate_uncertainty_contract({"selectedModelId": job["selectedModelId"], "modelFamily": decision["selectedModelFamily"],
                "parameterSha256": job["selectedModelParameterSha256"], "candidateRegistrySha256": decision["candidateRegistrySha256"],
                "featureOrderSha256": decision["featureOrderSha256"], "foldPlanSha256": decision["foldPlanSha256"],
                "datasetId": decision["datasetId"], "policyId": DECISION_POLICY_ID, "policyVersion": decision["decisionPolicyVersion"],
                "sourceFamily": "approved_forecast_p2", "forecastPresentationMode": uncertainty["forecastPresentationMode"],
                "calibrationStatus": uncertainty["calibrationStatus"], "lower": uncertainty["lowerRaw"], "upper": uncertainty["upperRaw"],
                "uncertaintyReasonCode": uncertainty["uncertaintyReasonCode"], "calibrationProvenance": uncertainty["calibrationProvenance"]}, ROOT)
        except UncertaintyContractError as exc:
            raise ApprovedForecastCommitError("The model-specific uncertainty contract is invalid.") from exc
        for value in (forecast, uncertainty, run, card):
            _same(value.get("forecastPresentationMode"), "point_only", "Forecast presentation mode changed.")
            _same(value.get("calibrationStatus"), "pending", "Calibration status changed.")
            _same(value.get("uncertaintyReasonCode"), "model_specific_calibration_pending", "Uncertainty reason changed.")
        _same(uncertainty.get("lowerRaw"), None, "Point-only lower bound must be null.")
        _same(uncertainty.get("upperRaw"), None, "Point-only upper bound must be null.")
        _same(uncertainty.get("calibrationProvenance"), None, "Point-only calibration provenance must be null.")
        _same(uncertainty.get("modelFamily"), decision.get("selectedModelFamily"), "Uncertainty model family changed.")
        _same(uncertainty.get("preprocessingIdentity"), decision.get("selectedModelPreprocessingIdentity"), "Uncertainty preprocessing changed.")
        _same(uncertainty.get("candidateRegistrySha256"), decision.get("candidateRegistrySha256"), "Uncertainty registry changed.")
        _same(uncertainty.get("featureOrderSha256"), decision.get("featureOrderSha256"), "Uncertainty feature order changed.")
        _same(uncertainty.get("foldPlanSha256"), decision.get("foldPlanSha256"), "Uncertainty fold plan changed.")
    return {"assessmentPolicy": assessment_policy, "decisionPolicy": decision_policy,
            "candidateRegistrySha256": policy["candidateRegistrySha256"], "technicalWinnerModelId": decision["technicalWinnerModelId"],
            "technicalWinnerParameterSha256": decision["technicalWinnerParameterSha256"], "labelledRows": labelled_rows,
            "plannedFolds": planned_folds, "successfulFolds": planned_folds, "failedFolds": 0,
            "foldPlanSha256": summary["foldPlanSha256"], "selectedEvaluationPeriod": evaluation_period,
            "trainingRowCount": labelled_rows, "trainingPeriod": rebuilt_period, "featureMatrixSha256": matrix_sha,
            "featureOrderSha256": summary["provenance"]["featureOrderSha256"],
            "authorizationCommitSha256": authorization_commit_sha}


def _verify_phase_one(root: Path, staging: Path, job: dict[str, Any], run: dict[str, Any],
                      forecast: dict[str, Any], card: dict[str, Any]) -> None:
    decision_root = require_within(root, root / "decisions" / job["decisionId"], "decision")
    decision_path, decision_commit_path = decision_root / "decision.json", decision_root / "commit.json"
    decision, decision_commit = _json(decision_path), _json(decision_commit_path)
    _same(sha256_file(decision_commit_path), job["decisionCommitSha256"], "Historical decision commit binding changed.")
    _same(decision_commit.get("decisionSha256"), sha256_file(decision_path), "Historical decision artifact hash changed.")
    policy, phase_two = _verify_policy(decision)
    if phase_two or run.get("schemaVersion") != "1.0":
        raise ApprovedForecastCommitError("A schema 1.0 run cannot use Phase 2 evidence.")
    assessment_root = require_within(root, root / "assessments" / job["assessmentId"], "assessment")
    assessment_commit_path = assessment_root / "metadata/commit.json"
    assessment_commit = _json(assessment_commit_path)
    _same(sha256_file(assessment_commit_path), job["assessmentCommitSha256"], "Historical assessment commit binding changed.")
    evidence: dict[str, dict[str, Any]] = {}
    for name in ("assessment_summary.json", "candidate_model_comparison.json", "rolling_validation.json"):
        path = assessment_root / "artifacts" / name
        _same(assessment_commit.get("artifactHashes", {}).get(name), sha256_file(path), f"Historical assessment artifact changed: {name}.")
        evidence[name] = _json(path)
    summary, comparison, rolling = (evidence["assessment_summary.json"], evidence["candidate_model_comparison.json"],
                                    evidence["rolling_validation.json"])
    selected = next((value for value in summary.get("candidates", []) if value.get("modelId") == job["selectedModelId"]), None)
    compared = next((value for value in comparison.get("candidates", []) if value.get("modelId") == job["selectedModelId"]), None)
    winner = next((value for value in summary.get("candidates", []) if value.get("modelId") == summary.get("technicalWinnerModelId")), None)
    checks = (
        (rolling.get("assessmentPolicy"), {"policyId": ASSESSMENT_POLICY_ID, "policyVersion": "p1.4d-1-v1",
                                           "policySha256": P1_ASSESSMENT_SHA}, "Historical assessment policy changed."),
        (summary.get("labelledRows"), 173, "Historical labelled-row count changed."),
        (summary.get("foldPolicy", {}).get("plannedFoldCount"), 68, "Historical planned-fold count changed."),
        (rolling.get("plannedFoldCount"), 68, "Historical rolling fold count changed."),
        (comparison.get("plannedFoldCount"), 68, "Historical comparison fold count changed."),
        (len(rolling.get("folds", [])), 68, "Historical rolling evidence is incomplete."),
        (comparison.get("technicalWinnerModelId"), summary.get("technicalWinnerModelId"), "Historical technical winner changed."),
        (decision.get("technicalWinnerModelId"), summary.get("technicalWinnerModelId"), "Historical decision winner changed."),
        (decision.get("technicalWinnerParameterSha256"), (winner or {}).get("parametersSha256"), "Historical winner hash changed."),
        ((selected or {}).get("parametersSha256"), job["selectedModelParameterSha256"], "Historical selected-model hash changed."),
        ((compared or {}).get("parametersSha256"), job["selectedModelParameterSha256"], "Historical comparison model hash changed."),
        ((selected or {}).get("successfulFolds"), 68, "Historical selected-model fold coverage changed."),
        ((selected or {}).get("failedFolds"), 0, "Historical selected model has failed folds."),
        (forecast.get("trainingDataIdentity", {}).get("trainingRowCount"), 173, "Historical training-row count changed."),
        (card.get("assessment", {}).get("foldCount"), 68, "Historical model-card fold count changed."),
        (card.get("model", {}).get("candidateRegistrySha256"), policy["candidateRegistrySha256"], "Historical registry hash changed."),
    )
    for actual, expected, message in checks:
        _same(actual, expected, message)
    matrix_path = staging / "artifacts/model_features.csv"
    with matrix_path.open("r", encoding="utf-8", newline="") as handle:
        if sum(1 for _ in csv.DictReader(handle)) != 173:
            raise ApprovedForecastCommitError("Historical rebuilt training matrix is not exactly 173 rows.")
    auth_root = require_within(root, root / "authorizations" / job["authorizationId"], "authorization")
    authorization_path, authorization_commit_path = auth_root / "authorization.json", auth_root / "commit.json"
    authorization, authorization_commit = _json(authorization_path), _json(authorization_commit_path)
    _same(authorization_commit.get("authorizationSha256"), sha256_file(authorization_path), "Historical authorization hash changed.")
    _same(authorization.get("decisionCommitSha256"), job["decisionCommitSha256"], "Historical authorization decision binding changed.")
    _same(authorization.get("assessmentCommitSha256"), job["assessmentCommitSha256"], "Historical authorization assessment binding changed.")
    _same(authorization.get("selectedModelId"), job["selectedModelId"], "Historical authorization model changed.")
    _same(authorization.get("selectedModelParameterSha256"), job["selectedModelParameterSha256"], "Historical authorization parameter hash changed.")
    _same(authorization.get("scope"), "one_run", "Historical authorization scope changed.")
    if datetime.fromisoformat(authorization["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc):
        raise ApprovedForecastCommitError("The historical authorization expired before commit.")


def commit_approved_forecast(runtime_root: Path, staging_path: Path, job: dict[str, Any]) -> dict[str, Any]:
    root = require_absolute_directory(runtime_root, "runtime root")
    staging = require_within(root, staging_path, "approved forecast staging")
    if staging.parent != (root / "staging").resolve() or staging.name != job["runId"]:
        raise ApprovedForecastCommitError("Approved forecast staging identity mismatch.")
    artifacts = staging / "artifacts"
    present = {path.name for path in artifacts.iterdir()}
    missing, prohibited = REQUIRED - present, PROHIBITED & present
    if missing or prohibited:
        raise ApprovedForecastCommitError(f"Invalid approved forecast artifact set; missing={sorted(missing)}, prohibited={sorted(prohibited)}")
    values = {relative: _validate(staging / relative, schema) for relative, schema in SCHEMAS.items()}
    run, forecast = values["metadata/run.json"], values["artifacts/forecast_output.json"]
    uncertainty, dashboard, card = values["artifacts/forecast_uncertainty.json"], values["artifacts/dashboard_summary.json"], values["artifacts/model_card.json"]
    for value in (run, forecast):
        for key in ("runId", "jobId", "datasetId", "deploymentId", "decisionId", "assessmentId", "authorizationId"):
            _same(value.get(key), job.get(key), f"Approved forecast identity mismatch: {key}.")
    for key in ("runId", "jobId", "datasetId", "deploymentId", "decisionId", "assessmentId"):
        _same(uncertainty.get(key), job.get(key), f"Approved uncertainty identity mismatch: {key}.")
    if (any(card.get(key) != job.get(key) for key in ("runId", "jobId", "datasetId", "deploymentId"))
            or card.get("decision", {}).get("id") != job["decisionId"]
            or card.get("assessment", {}).get("id") != job["assessmentId"]
            or card.get("authorization", {}).get("id") != job["authorizationId"]):
        raise ApprovedForecastCommitError("Approved model-card identity mismatch.")
    if (forecast["selectedModelId"] != job["selectedModelId"]
            or forecast["selectedModelParameterSha256"] != job["selectedModelParameterSha256"]
            or forecast["deploymentModelAdopted"] is not False):
        raise ApprovedForecastCommitError("Selected model or adoption identity mismatch.")
    if (any(uncertainty.get(key) is not None for key in ("lowerRaw", "upperRaw", "lowerReported", "upperReported",
            "nominalCoverage", "historicalCoverage", "calibrationMethod", "residualCount"))
            or uncertainty.get("isPredictionInterval") is not False or uncertainty.get("rmseFallbackAllowed") is not False
            or uncertainty.get("bundledP13RangeReused") is not False):
        raise ApprovedForecastCommitError("Approved forecast uncertainty must remain null and uncalibrated.")
    if dashboard.get("preparedness") != {"availabilityStatus": "unavailable_missing_planning_policy", "scenarios": None,
                                            "counts": None, "facilities": [], "alerts": []}:
        raise ApprovedForecastCommitError("Approved forecast preparedness must remain unavailable.")

    state = require_within(root, root / "authorization-state" / job["authorizationId"], "authorization state")
    reservation = _json(state / "reservation.json")
    if (reservation.get("authorizationId") != job["authorizationId"] or reservation.get("decisionId") != job["decisionId"]
            or reservation.get("jobId") != job["jobId"] or reservation.get("runId") != job["runId"]
            or reservation.get("eventType") != "reserved" or (state / "consumption.json").exists()):
        raise ApprovedForecastCommitError("One-run authorization reservation is invalid or consumed.")
    if (sha256_file(root / "decisions" / job["decisionId"] / "commit.json") != job["decisionCommitSha256"]
            or sha256_file(root / "assessments" / job["assessmentId"] / "metadata/commit.json") != job["assessmentCommitSha256"]):
        raise ApprovedForecastCommitError("Decision or assessment commit binding changed.")

    phase_two = run.get("schemaVersion") == "2.0"
    if forecast.get("schemaVersion") != run.get("schemaVersion") or card.get("schemaVersion") != run.get("schemaVersion"):
        raise ApprovedForecastCommitError("Approved forecast artifact schema versions are mixed.")
    reconciliation = _verify_phase_two(root, staging, job, run, forecast, uncertainty, card) if phase_two else None
    if not phase_two and run.get("schemaVersion") != "1.0":
        raise ApprovedForecastCommitError("Unknown approved forecast schema version.")
    if not phase_two:
        _verify_phase_one(root, staging, job, run, forecast, card)

    hashes = {name: sha256_file(artifacts / name) for name in sorted(REQUIRED)}
    for name, digest in hashes.items():
        if name != "model_card.json" and card["artifactHashes"].get(name) != digest:
            raise ApprovedForecastCommitError(f"Model-card artifact hash mismatch: {name}.")
    if run["artifactPublicationSequence"][-1] != "model_card.json":
        raise ApprovedForecastCommitError("Approved forecast model card was not published last.")
    committed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    commit = {"schemaVersion": run["schemaVersion"], "runId": job["runId"], "jobId": job["jobId"],
              "datasetId": job["datasetId"], "deploymentId": job["deploymentId"],
              "workflowMode": "approved_assessment_forecast", "sourceType": "uploaded", "decisionId": job["decisionId"],
              "decisionCommitSha256": job["decisionCommitSha256"], "assessmentId": job["assessmentId"],
              "assessmentCommitSha256": job["assessmentCommitSha256"], "authorizationId": job["authorizationId"],
              "selectedModelId": job["selectedModelId"], "selectedModelParameterSha256": job["selectedModelParameterSha256"],
              "decisionScope": "one_run", "deploymentModelAdopted": False, "status": "committed", "artifactHashes": hashes,
              "modelCardPublishedLast": True, "prohibitedArtifactsAbsent": True, "committedAt": committed_at}
    if reconciliation:
        commit.update({"authorizationCommitSha256": reconciliation["authorizationCommitSha256"],
                       "assessmentPolicy": reconciliation["assessmentPolicy"], "decisionPolicy": reconciliation["decisionPolicy"],
                       "candidateRegistrySha256": reconciliation["candidateRegistrySha256"],
                       "technicalWinnerModelId": reconciliation["technicalWinnerModelId"],
                       "technicalWinnerParameterSha256": reconciliation["technicalWinnerParameterSha256"],
                       "assessmentLabelledRows": reconciliation["labelledRows"],
                       "assessmentPlannedFoldCount": reconciliation["plannedFolds"],
                       "successfulFolds": reconciliation["successfulFolds"], "failedFolds": reconciliation["failedFolds"],
                       "foldPlanSha256": reconciliation["foldPlanSha256"],
                       "selectedEvaluationPeriod": reconciliation["selectedEvaluationPeriod"],
                       "trainingRowCount": reconciliation["trainingRowCount"], "trainingPeriod": reconciliation["trainingPeriod"],
                       "featureMatrixSha256": reconciliation["featureMatrixSha256"],
                       "featureOrderSha256": reconciliation["featureOrderSha256"], "target": forecast["target"],
                       "horizonWeeks": forecast["horizonWeeks"], "forecastRaw": forecast["forecastRaw"],
                       "forecastReported": forecast["forecastReported"],
                       "forecastOutputSha256": hashes["forecast_output.json"], "modelCardSha256": hashes["model_card.json"],
                       "runRecordSha256": sha256_file(staging / "metadata/run.json"), "completeReconciliation": True})
        if reconciliation["decisionPolicy"]["policyVersion"] == "p2-v2":
            commit.update({"selectedModelFamily": forecast["selectedModelFamily"],
                           "selectedModelPreprocessingIdentity": forecast["selectedModelPreprocessingIdentity"],
                           "selectionType": forecast["selectionType"],
                           "forecastPresentationMode": forecast["forecastPresentationMode"],
                           "calibrationStatus": forecast["calibrationStatus"],
                           "uncertaintyReasonCode": forecast["uncertaintyReasonCode"]})
    schema = _json(ROOT / "config/runtime_approved_forecast_commit.schema.json")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(commit))
    if errors:
        raise ApprovedForecastCommitError(f"Approved forecast commit failed schema validation: {errors[0].message}")
    atomic_json(staging / "metadata/commit.json", commit)

    runs = (root / "runs").resolve()
    runs.mkdir(parents=True, exist_ok=True)
    committed = runs / job["runId"]
    if committed.exists():
        raise ApprovedForecastCommitError("Immutable approved forecast run already exists.")
    os.replace(staging, committed)
    _fsync(runs)
    _immutable(committed)
    deployment = root / "deployments" / job["deploymentId"]
    lock_path = deployment / "locks/commit.lock"
    descriptor = _lock(lock_path)
    try:
        pointer = {"schemaVersion": "1.0", "deploymentId": job["deploymentId"], "runId": job["runId"],
                   "datasetId": job["datasetId"], "workflowMode": "approved_assessment_forecast", "sourceType": "uploaded",
                   "decisionId": job["decisionId"], "assessmentId": job["assessmentId"],
                   "authorizationId": job["authorizationId"], "selectedModelId": job["selectedModelId"],
                   "committedAt": committed_at, "modelCardSha256": sha256_file(committed / "artifacts/model_card.json"),
                   "dashboardSummarySha256": sha256_file(committed / "artifacts/dashboard_summary.json"),
                   "commitRecordSha256": sha256_file(committed / "metadata/commit.json")}
        Draft202012Validator(_json(ROOT / "config/runtime_latest.schema.json"), format_checker=FormatChecker()).validate(pointer)
        deployment.mkdir(parents=True, exist_ok=True)
        atomic_json(deployment / "latest.json", pointer)
        _fsync(deployment)
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)
    consumption = {"schemaVersion": "1.0", "authorizationId": job["authorizationId"], "decisionId": job["decisionId"],
                   "eventType": "consumed", "eventId": str(uuid.uuid4()), "createdAt": committed_at,
                   "jobId": job["jobId"], "runId": job["runId"]}
    try:
        atomic_json(state / "consumption.json", consumption)
    except Exception:
        pass
    return {"runRoot": str(committed), "pointer": pointer, "commit": commit}
