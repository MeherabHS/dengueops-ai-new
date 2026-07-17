"""Execute one immutable-assessment-authorized point forecast."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker
from sklearn.exceptions import ConvergenceWarning

from feature_engineering import FEATURE_COLUMNS, build_features, build_inference_features
from model_factory import build_candidate_estimator, canonical_sha256, load_and_validate_candidate_registry
from runtime_approved_forecast_commit import commit_approved_forecast
from runtime_assessment_policy import load_and_validate_assessment_policy
from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_validate import HORIZON_WEEKS, TARGET, compute_dataset_id


P1_ASSESSMENT_SHA = "dbf9d4cc4713bbb9d114b2dab916d0f20b3004ac14b37ca663c3caecefcea0af"
P2_ASSESSMENT_SHA = "04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff"
P1_DECISION_SHA = "8fece340b85951d3bee8b037c4ac79ae82636ee371a934e9371bcb4a633491a4"
P2_DECISION_SHA = "aaef2ed2afd3afe03a0aec91889f144a3274cad21aa8cef8ef772bb90cfdcb4a"
ASSESSMENT_POLICY_ID = "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE"
DECISION_POLICY_ID = "RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION"
DEPLOYABLE = {"ridge_regression", "poisson_regression", "random_forest", "gradient_boosting"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be an object.")
    return value


def _period(year: int, week: int) -> str:
    return f"{year}-W{week:02d}"


def _advance(year: int, week: int, count: int) -> tuple[int, int]:
    offset = year * 52 + week - 1 + count
    return offset // 52, offset % 52 + 1


def _update(path: Path, job: dict[str, Any], **changes: Any) -> None:
    job.update(changes)
    job["updatedAt"] = _now()
    atomic_json(path, job)


def _write(path: Path, value: Any) -> None:
    atomic_json(path, value)


def _canonical_policy_sha256(policy: dict[str, Any]) -> str:
    content = dict(policy)
    content.pop("policySha256", None)
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_decision_policy(decision: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    identity = (
        decision.get("schemaVersion"), decision.get("assessmentPolicyId"),
        decision.get("assessmentPolicyVersion"), decision.get("assessmentPolicySha256"),
        decision.get("decisionPolicyId"), decision.get("decisionPolicyVersion"),
        decision.get("decisionPolicySha256"),
    )
    p1 = ("1.0", ASSESSMENT_POLICY_ID, "p1.4d-1-v1", P1_ASSESSMENT_SHA,
          DECISION_POLICY_ID, "p1.4d-3-e-v1", P1_DECISION_SHA)
    p2 = ("2.0", ASSESSMENT_POLICY_ID, "p2-v1", P2_ASSESSMENT_SHA,
          DECISION_POLICY_ID, "p2-v1", P2_DECISION_SHA)
    if identity == p1:
        filename, phase_two = "decision_policy_p1.4d-3-e-v1.json", False
    elif identity == p2:
        filename, phase_two = "decision_policy.json", True
    else:
        raise ValueError("The committed decision policy identity is unsupported or hybrid.")
    policy = _json(ROOT / "config" / "deployments" / "dhaka_south" / filename)
    schema = _json(ROOT / "config" / "runtime_decision_policy.schema.json")
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy))
    if errors or policy.get("policySha256") != _canonical_policy_sha256(policy):
        raise ValueError("The governed decision policy failed independent validation.")
    if (policy.get("policyId"), policy.get("policyVersion"), policy.get("policySha256")) != identity[4:]:
        raise ValueError("The governed decision policy resolution does not match the decision.")
    return policy, phase_two


def _artifact(assessment: Path, commit: dict[str, Any], name: str) -> dict[str, Any]:
    path = assessment / "artifacts" / name
    if commit.get("artifactHashes", {}).get(name) != sha256_file(path):
        raise ValueError(f"The immutable assessment artifact changed: {name}.")
    return _json(path)


def _policy_evidence(identifier: str, version: str, digest: str) -> dict[str, str]:
    return {"policyId": identifier, "policyVersion": version, "policySha256": digest}


def execute(args: argparse.Namespace) -> dict[str, Any]:
    root = require_absolute_directory(args.runtime_root, "runtime root")
    job_path = require_within(root, args.job_record, "job record")
    assessment = require_within(root, args.assessment, "assessment")
    staging = require_within(root, args.staging, "staging")
    job = _json(job_path)
    if (job.get("jobKind") != "approved_forecast" or job.get("status") != "running"
            or job.get("workflowMode") != "approved_assessment_forecast"
            or staging.parent != (root / "staging").resolve()
            or assessment.parent != (root / "assessments").resolve()):
        raise ValueError("The approved forecast job or paths are invalid.")

    _update(job_path, job, progress="verifying_decision")
    decision_root = require_within(root, root / "decisions" / job["decisionId"], "decision")
    decision_path, decision_commit_path = decision_root / "decision.json", decision_root / "commit.json"
    decision, decision_commit = _json(decision_path), _json(decision_commit_path)
    decision_commit_sha = sha256_file(decision_commit_path)
    if (decision_commit_sha != job["decisionCommitSha256"]
            or decision_commit.get("decisionSha256") != sha256_file(decision_path)
            or decision_commit.get("decisionId") != decision.get("decisionId")
            or decision.get("authorizationId") != job["authorizationId"]
            or decision.get("selectedModelId") != job["selectedModelId"]
            or decision.get("selectedModelParameterSha256") != job["selectedModelParameterSha256"]
            or decision.get("forecastAuthorized") is not True):
        raise ValueError("The immutable decision binding is invalid.")
    policy, phase_two = _load_decision_policy(decision)

    auth_root = require_within(root, root / "authorizations" / job["authorizationId"], "authorization")
    authorization_path, authorization_commit_path = auth_root / "authorization.json", auth_root / "commit.json"
    authorization, auth_commit = _json(authorization_path), _json(authorization_commit_path)
    authorization_commit_sha = sha256_file(authorization_commit_path)
    reservation = _json(root / "authorization-state" / job["authorizationId"] / "reservation.json")
    if (auth_commit.get("authorizationSha256") != sha256_file(authorization_path)
            or auth_commit.get("decisionCommitSha256") != decision_commit_sha
            or authorization.get("decisionCommitSha256") != decision_commit_sha
            or authorization.get("decisionId") != decision["decisionId"]
            or authorization.get("assessmentId") != decision["assessmentId"]
            or authorization.get("assessmentCommitSha256") != decision["assessmentCommitSha256"]
            or authorization.get("selectedModelId") != decision["selectedModelId"]
            or authorization.get("selectedModelParameterSha256") != decision["selectedModelParameterSha256"]
            or authorization.get("scope") != "one_run" or authorization.get("initialStatus") != "available"
            or datetime.fromisoformat(authorization["expiresAt"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
            or reservation.get("authorizationId") != authorization["authorizationId"]
            or reservation.get("decisionId") != decision["decisionId"]
            or reservation.get("eventType") != "reserved"
            or reservation.get("jobId") != job["jobId"] or reservation.get("runId") != job["runId"]):
        raise ValueError("The one-run authorization is invalid.")

    _update(job_path, job, progress="verifying_assessment")
    assessment_commit_path = assessment / "metadata" / "commit.json"
    if sha256_file(assessment_commit_path) != job["assessmentCommitSha256"]:
        raise ValueError("The immutable assessment commit changed.")
    assessment_commit = _json(assessment_commit_path)
    summary = _artifact(assessment, assessment_commit, "assessment_summary.json")
    comparison = _artifact(assessment, assessment_commit, "candidate_model_comparison.json")
    rolling = _artifact(assessment, assessment_commit, "rolling_validation.json")
    if (summary.get("assessmentId") != job["assessmentId"] or summary.get("datasetId") != job["datasetId"]
            or decision.get("assessmentId") != summary.get("assessmentId")
            or decision.get("assessmentCommitSha256") != job["assessmentCommitSha256"]
            or decision.get("assessmentSummarySha256") != sha256_file(assessment / "artifacts" / "assessment_summary.json")
            or decision.get("comparisonSha256") != sha256_file(assessment / "artifacts" / "candidate_model_comparison.json")
            or decision.get("foldPlanSha256") != summary.get("foldPlanSha256")
            or comparison.get("foldPlanSha256") != summary.get("foldPlanSha256")
            or rolling.get("foldPlanSha256") != summary.get("foldPlanSha256")):
        raise ValueError("The immutable assessment evidence is invalid.")

    assessment_version = "p2-v1" if phase_two else "p1.4d-1-v1"
    assessment_sha = P2_ASSESSMENT_SHA if phase_two else P1_ASSESSMENT_SHA
    load_and_validate_assessment_policy("dhaka_south", assessment_version, assessment_sha)
    assessment_policy = rolling.get("assessmentPolicy", {})
    if assessment_policy != _policy_evidence(ASSESSMENT_POLICY_ID, assessment_version, assessment_sha):
        raise ValueError("The assessment policy evidence is invalid.")

    candidates = summary.get("candidates", [])
    comparison_candidates = comparison.get("candidates", [])
    candidate = next((value for value in candidates if value.get("modelId") == job["selectedModelId"]), None)
    compared = next((value for value in comparison_candidates if value.get("modelId") == job["selectedModelId"]), None)
    winner = next((value for value in candidates if value.get("modelId") == summary.get("technicalWinnerModelId")), None)
    compared_winner = next((value for value in comparison_candidates if value.get("modelId") == comparison.get("technicalWinnerModelId")), None)
    if (not candidate or not compared or job["selectedModelId"] not in DEPLOYABLE
            or candidate.get("deployabilityClass") != "deployable_learned_model"
            or candidate.get("completionStatus") != "complete" or candidate.get("selectionEligible") is not True
            or candidate.get("parametersSha256") != job["selectedModelParameterSha256"]
            or candidate.get("parametersSha256") != compared.get("parametersSha256")
            or candidate.get("successfulFolds") != compared.get("successfulFolds")
            or candidate.get("failedFolds") != compared.get("failedFolds")
            or summary.get("technicalWinnerModelId") != comparison.get("technicalWinnerModelId")
            or bool(winner) != bool(compared_winner)
            or (winner and winner.get("parametersSha256") != compared_winner.get("parametersSha256"))
            or decision.get("technicalWinnerModelId") != summary.get("technicalWinnerModelId")
            or decision.get("technicalWinnerParameterSha256") != (winner or {}).get("parametersSha256")):
        raise ValueError("The selected model or technical winner does not reconcile to committed comparison evidence.")

    if phase_two:
        labelled_rows = summary.get("labelledRows")
        planned_folds = summary.get("foldPolicy", {}).get("plannedFoldCount")
        evaluation_period = summary.get("foldPolicy", {}).get("selectedEvaluationPeriod")
        if (not isinstance(labelled_rows, int) or labelled_rows < 157
                or not isinstance(planned_folds, int) or not 52 <= planned_folds <= 68
                or decision.get("assessmentSchemaVersion") != "2.0"
                or decision.get("assessmentLabelledRows") != labelled_rows
                or decision.get("assessmentPlannedFoldCount") != planned_folds
                or decision.get("selectedEvaluationPeriod") != evaluation_period
                or assessment_commit.get("assessmentPolicyId") != ASSESSMENT_POLICY_ID
                or assessment_commit.get("assessmentPolicyVersion") != "p2-v1"
                or assessment_commit.get("assessmentPolicySha256") != assessment_sha
                or assessment_commit.get("candidateRegistrySha256") != decision.get("candidateRegistrySha256")
                or comparison.get("candidateRegistrySha256") != decision.get("candidateRegistrySha256")
                or rolling.get("candidateRegistrySha256") != decision.get("candidateRegistrySha256")
                or comparison.get("plannedFoldCount") != planned_folds
                or rolling.get("plannedFoldCount") != planned_folds
                or len(rolling.get("folds", [])) != planned_folds
                or comparison.get("labelledRows") != labelled_rows or rolling.get("labelledRows") != labelled_rows
                or comparison.get("selectedEvaluationPeriod") != evaluation_period
                or rolling.get("selectedEvaluationPeriod") != evaluation_period
                or candidate.get("successfulFolds") != planned_folds or candidate.get("failedFolds") != 0):
            raise ValueError("The Phase 2 row, fold, policy, or selected-period evidence is invalid.")
        for key in ("assessmentPolicyId", "assessmentPolicyVersion", "assessmentPolicySha256",
                    "decisionPolicyId", "decisionPolicyVersion", "decisionPolicySha256",
                    "assessmentLabelledRows", "assessmentPlannedFoldCount", "foldPlanSha256"):
            if authorization.get(key) != decision.get(key):
                raise ValueError("The Phase 2 authorization evidence does not reconcile.")
    else:
        labelled_rows, planned_folds = 173, 68
        evaluation_period = summary.get("foldPolicy", {}).get("selectedEvaluationPeriod")
        if summary.get("labelledRows") != 173 or summary.get("foldPolicy", {}).get("plannedFoldCount") != 68:
            raise ValueError("The historical Phase 1 assessment shape changed.")

    canonical_case = assessment / "inputs" / "canonical" / "dengue_cases.csv"
    canonical_climate = assessment / "inputs" / "canonical" / "climate_data.csv"
    validation_path = assessment / "metadata" / "validation.json"
    validation = _json(validation_path)
    feature_hash = summary["provenance"]["featureOrderSha256"]
    if (sha256_file(validation_path) != job["validationRecordSha256"]
            or validation.get("counts", {}).get("labelledRows") != labelled_rows
            or compute_dataset_id(canonical_case.read_bytes(), canonical_climate.read_bytes(), job["deploymentId"], feature_hash) != job["datasetId"]):
        raise ValueError("Assessment input identity no longer matches the decision.")
    if staging.exists() and {path.name for path in staging.iterdir()} - {"logs"}:
        raise ValueError("Approved forecast staging contains unexpected content.")
    for relative in ("metadata", "inputs/original", "inputs/canonical", "artifacts"):
        (staging / relative).mkdir(parents=True, exist_ok=False if relative == "metadata" else True)
    _update(job_path, job, progress="loading_immutable_inputs")
    for source, target in (
        (assessment / "inputs/original/dengue.csv", staging / "inputs/original/dengue.csv"),
        (assessment / "inputs/original/climate.csv", staging / "inputs/original/climate.csv"),
        (canonical_case, staging / "inputs/canonical/dengue_cases.csv"),
        (canonical_climate, staging / "inputs/canonical/climate_data.csv"),
        (validation_path, staging / "metadata/validation.json"),
    ):
        shutil.copy2(source, target)

    _update(job_path, job, progress="building_features")
    training, _ = build_features(canonical_case, canonical_climate, output_path=None)
    inference = build_inference_features(canonical_case, canonical_climate)
    if (len(training) != labelled_rows or (not phase_two and len(training) != 173) or inference.empty
            or list(training[FEATURE_COLUMNS].columns) != list(FEATURE_COLUMNS)
            or canonical_sha256(list(FEATURE_COLUMNS)) != feature_hash):
        raise ValueError("The governed full-training feature contract is unavailable.")
    X = training[FEATURE_COLUMNS].apply(pd.to_numeric, errors="raise")
    y = pd.to_numeric(training[TARGET], errors="raise")
    latest = inference.iloc[-1]
    x_latest = latest[FEATURE_COLUMNS].to_frame().T.astype(float)
    if (not np.isfinite(X.to_numpy()).all() or not np.isfinite(y.to_numpy()).all()
            or (y < 0).any() or not np.isfinite(x_latest.to_numpy()).all()):
        raise ValueError("Approved forecast training data contains invalid values.")
    registry, registry_hash = load_and_validate_candidate_registry()
    if registry_hash != summary["provenance"]["candidateRegistrySha256"] or registry_hash != policy["candidateRegistrySha256"]:
        raise ValueError("Candidate registry identity changed after assessment.")
    registry_candidate = next(value for value in registry["candidates"] if value["model_id"] == job["selectedModelId"])
    if registry_candidate["parameters_sha256"] != job["selectedModelParameterSha256"]:
        raise ValueError("Selected-model parameter identity changed.")

    _update(job_path, job, progress="training_selected_model")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        estimator = build_candidate_estimator(job["selectedModelId"], registry)
        estimator.fit(X, y)
        raw = float(estimator.predict(x_latest)[0])
    if any(issubclass(item.category, ConvergenceWarning) for item in caught):
        raise ValueError("Selected model emitted an unresolved convergence warning.")
    if not math.isfinite(raw) or (job["selectedModelId"] in {"poisson_regression", "random_forest"} and raw < 0):
        raise ValueError("Selected model returned an invalid point forecast.")

    published = max(0.0, raw)
    reported = int(round(published))
    latest_cases = int(latest["cases"])
    direction = "Increasing" if reported > latest_cases else "Decreasing" if reported < latest_cases else "Stable"
    target_year, target_week = _advance(int(latest["epi_year"]), int(latest["epi_week"]), HORIZON_WEEKS)
    target_period, generated = _period(target_year, target_week), _now()
    feature_bytes = training.to_csv(index=False, lineterminator="\n").encode()
    feature_matrix_hash = hashlib.sha256(feature_bytes).hexdigest()
    training_period = {"start": _period(int(training.iloc[0]["epi_year"]), int(training.iloc[0]["epi_week"])),
                       "end": _period(int(training.iloc[-1]["epi_year"]), int(training.iloc[-1]["epi_week"]))}
    training_identity = {"datasetId": job["datasetId"], "featureMatrixSha256": feature_matrix_hash,
                         "trainingRowCount": len(training), "trainingPeriod": training_period,
                         "featureOrderSha256": feature_hash, "library": "scikit-learn"}
    schema_version = "2.0" if phase_two else "1.0"
    assessment_policy_evidence = _policy_evidence(ASSESSMENT_POLICY_ID, assessment_version, assessment_sha)
    decision_policy_evidence = _policy_evidence(DECISION_POLICY_ID, policy["policyVersion"], policy["policySha256"])
    governance = {"assessmentCommitSha256": job["assessmentCommitSha256"], "decisionCommitSha256": decision_commit_sha,
                  "authorizationCommitSha256": authorization_commit_sha, "assessmentPolicy": assessment_policy_evidence,
                  "decisionPolicy": decision_policy_evidence, "candidateRegistrySha256": registry_hash,
                  "assessmentLabelledRows": labelled_rows, "assessmentPlannedFoldCount": planned_folds,
                  "successfulFolds": candidate["successfulFolds"], "failedFolds": candidate["failedFolds"],
                  "selectedEvaluationPeriod": evaluation_period, "foldPlanSha256": summary["foldPlanSha256"]}

    artifacts = staging / "artifacts"
    (artifacts / "model_features.csv").write_bytes(feature_bytes)
    _write(artifacts / "input_manifest.json", {"schemaVersion": schema_version, "runId": job["runId"],
           "assessmentId": job["assessmentId"], "datasetId": job["datasetId"],
           "validationRecordSha256": job["validationRecordSha256"], "canonicalDengueSha256": sha256_file(canonical_case),
           "canonicalClimateSha256": sha256_file(canonical_climate), "featureOrderSha256": feature_hash, "generatedAt": generated})
    _update(job_path, job, progress="generating_point_forecast")
    forecast = {"schemaVersion": schema_version, "runId": job["runId"], "jobId": job["jobId"],
                "datasetId": job["datasetId"], "deploymentId": job["deploymentId"], "sourceType": "uploaded",
                "workflowMode": "approved_assessment_forecast", "decisionId": job["decisionId"],
                "assessmentId": job["assessmentId"], "authorizationId": job["authorizationId"],
                "selectedModelId": job["selectedModelId"], "selectedModelParameterSha256": job["selectedModelParameterSha256"],
                "technicalWinnerModelId": decision["technicalWinnerModelId"], "decisionOutcome": decision["decision"],
                "selectionBasis": "immutable_dataset_assessment_and_internal_one_run_decision", "comparisonPerformed": True,
                "recommendationStrength": "not_available", "decisionScope": "one_run", "deploymentModelAdopted": False,
                "trainingDataIdentity": training_identity, "latestObservedCases": latest_cases, "forecastRaw": raw,
                "forecastReported": reported, "targetPeriod": target_period, "target": TARGET, "horizonWeeks": 2,
                "forecastGrowthCategory": direction, "reportingRoundingPolicy": "nearest_integer_python_round_half_to_even",
                "clippingApplied": raw != published, "generatedAt": generated,
                "uncertaintyStatus": "pending_selected_model_calibration", "preparednessStatus": "unavailable_missing_planning_policy"}
    if phase_two:
        forecast.update({"technicalWinnerParameterSha256": decision["technicalWinnerParameterSha256"],
                         "governanceEvidence": governance})
    _write(artifacts / "forecast_output.json", forecast)

    uncertainty = {"schemaVersion": "1.0", "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
                   "deploymentId": job["deploymentId"], "decisionId": job["decisionId"], "assessmentId": job["assessmentId"],
                   "selectedModelId": job["selectedModelId"], "selectedModelParameterSha256": job["selectedModelParameterSha256"],
                   "uncertaintyStatus": "pending_selected_model_calibration", "lowerRaw": None, "upperRaw": None,
                   "lowerReported": None, "upperReported": None, "nominalCoverage": None, "historicalCoverage": None,
                   "calibrationMethod": None, "residualCount": None, "isPredictionInterval": False,
                   "calibratedOnSyntheticData": False, "rmseFallbackAllowed": False, "bundledP13RangeReused": False,
                   "syntheticRangeReused": False, "limitations": ["Selected-model calibration has not been governed or executed.",
                   "Assessment residuals are retained as evidence but no interval is inferred from them."], "generatedAt": generated}
    _write(artifacts / "forecast_uncertainty.json", uncertainty)
    cases = pd.read_csv(canonical_case)
    history = [{"period": _period(int(row.epi_year), int(row.epi_week)), "cases": int(row.cases)} for row in cases.tail(52).itertuples()]
    _write(artifacts / "chart_data.json", {"schemaVersion": "1.0", "runId": job["runId"], "history": history,
                                           "forecast": {"period": target_period, "cases": reported}, "empiricalRange": None})
    dashboard = {"schemaVersion": "1.0", "run": {"runId": job["runId"], "jobId": job["jobId"],
                 "datasetId": job["datasetId"], "deploymentId": job["deploymentId"],
                 "workflowMode": "approved_assessment_forecast", "sourceType": "uploaded", "committedAt": generated,
                 "completedSteps": 7}, "model": {"modelId": job["selectedModelId"], "modelLabel": registry_candidate["model_family"],
                 "parameterHash": job["selectedModelParameterSha256"], "technicalWinnerModelId": decision["technicalWinnerModelId"],
                 "selectionBasis": "immutable_dataset_assessment_and_internal_one_run_decision", "comparisonPerformed": True,
                 "deploymentModelAdopted": False}, "decision": {"decisionId": job["decisionId"], "assessmentId": job["assessmentId"],
                 "authorizationId": job["authorizationId"], "outcome": decision["decision"], "scope": "one_run",
                 "operatorType": "trusted_internal_unverified", "institutionalApproval": False}, "forecast": {
                 "latestObservedCases": latest_cases, "forecastRaw": raw, "forecastReported": reported,
                 "targetPeriod": target_period, "target": TARGET, "horizonWeeks": 2, "direction": direction,
                 "uncertaintyStatus": "pending_selected_model_calibration", "empiricalLower": None, "empiricalUpper": None},
                 "history": history, "preparedness": {"availabilityStatus": "unavailable_missing_planning_policy", "scenarios": None,
                 "counts": None, "facilities": [], "alerts": []}, "evidence": {"validation": {"sha256": job["validationRecordSha256"],
                 "acceptedPeriod": validation.get("acceptedPeriod")}, "assessment": {"assessmentId": job["assessmentId"],
                 "commitSha256": job["assessmentCommitSha256"]}, "decision": {"decisionId": job["decisionId"],
                 "commitSha256": decision_commit_sha}, "modelCard": {"path": "artifacts/model_card.json"},
                 "provenance": {"datasetId": job["datasetId"], "inputManifest": "artifacts/input_manifest.json"}},
                 "limitations": ["Technical evidence only; recommendation strength is not available.",
                 "The trusted internal operator identity is not verified.",
                 "This decision authorizes one run and does not adopt a deployment model.",
                 "Uncertainty and preparedness are unavailable."]}
    _write(artifacts / "dashboard_summary.json", dashboard)
    _write(artifacts / "pipeline_run_summary.json", {"schemaVersion": schema_version, "runId": job["runId"],
           "jobId": job["jobId"], "status": "commit_ready", "steps": ["decision_verified", "assessment_verified",
           "features_built", "selected_model_trained", "point_forecast_generated", "artifacts_validated"],
           "candidateComparisonPerformed": True, "candidateComparisonExecutedInThisRun": False,
           "uncertaintyCalibrationPerformed": False, "operationalEngineExecuted": False, "generatedAt": generated})
    sequence = ["input_manifest.json", "model_features.csv", "forecast_output.json", "forecast_uncertainty.json",
                "chart_data.json", "dashboard_summary.json", "pipeline_run_summary.json", "model_card.json"]
    run = {"schemaVersion": schema_version, "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
           "deploymentId": job["deploymentId"], "workflowMode": "approved_assessment_forecast", "sourceType": "uploaded",
           "status": "commit_ready", "decisionId": job["decisionId"], "assessmentId": job["assessmentId"],
           "authorizationId": job["authorizationId"], "selectedModelId": job["selectedModelId"],
           "selectedModelParameterSha256": job["selectedModelParameterSha256"], "decisionScope": "one_run",
           "deploymentModelAdopted": False, "createdAt": job["createdAt"], "generatedAt": generated,
           "artifactPublicationSequence": sequence}
    if phase_two:
        run.update({"decisionCommitSha256": decision_commit_sha, "assessmentCommitSha256": job["assessmentCommitSha256"],
                    "authorizationCommitSha256": authorization_commit_sha, "assessmentPolicy": assessment_policy_evidence,
                    "decisionPolicy": decision_policy_evidence, "candidateRegistrySha256": registry_hash,
                    "assessmentLabelledRows": labelled_rows, "assessmentPlannedFoldCount": planned_folds,
                    "selectedEvaluationPeriod": evaluation_period, "foldPlanSha256": summary["foldPlanSha256"],
                    "trainingRowCount": len(training), "trainingPeriod": training_period,
                    "featureMatrixSha256": feature_matrix_hash, "featureOrderSha256": feature_hash})
    _write(staging / "metadata/run.json", run)
    hashes = {name: sha256_file(artifacts / name) for name in sequence if name != "model_card.json"}
    card = {"schemaVersion": schema_version, "runId": job["runId"], "jobId": job["jobId"], "datasetId": job["datasetId"],
            "deploymentId": job["deploymentId"], "workflowMode": "approved_assessment_forecast", "sourceType": "uploaded",
            "decision": {"id": job["decisionId"], "commitSha256": decision_commit_sha, "outcome": decision["decision"],
            "operatorType": "trusted_internal_unverified"}, "assessment": {"id": job["assessmentId"],
            "commitSha256": job["assessmentCommitSha256"], "foldCount": planned_folds, "recommendationStrength": "not_available"},
            "authorization": {"id": job["authorizationId"], "scope": "one_run"}, "model": {"id": job["selectedModelId"],
            "family": registry_candidate["model_family"], "parameterHash": job["selectedModelParameterSha256"],
            "candidateRegistrySha256": registry_hash, "runtimeLibrary": "scikit-learn"}, "features": {"count": 18,
            "orderSha256": feature_hash}, "target": TARGET, "horizonWeeks": 2, "training": training_identity,
            "comparisonPerformed": True, "recommendationStrength": "not_available", "decisionScope": "one_run",
            "deploymentModelAdopted": False, "operatorType": "trusted_internal_unverified", "institutionalApproval": False,
            "uncertaintyStatus": "pending_selected_model_calibration", "preparednessStatus": "unavailable_missing_planning_policy",
            "inputHashes": {"canonicalDengue": sha256_file(canonical_case), "canonicalClimate": sha256_file(canonical_climate),
            "assessmentCommit": job["assessmentCommitSha256"], "decisionCommit": decision_commit_sha}, "artifactHashes": hashes,
            "commitReadiness": "ready_for_runtime_commit", "intendedUse": "Model selected through a trusted internal decision bound to immutable dataset-specific assessment evidence for one forecast run.",
            "limitations": [f"Technical comparison was performed on {planned_folds} governed temporal folds.",
            "Recommendation strength was not governed.", "This decision authorizes one forecast run only.",
            "This does not constitute deployment-wide model adoption.", "Operator identity and institutional approval are not verified.",
            "Uncertainty calibration has not been completed and preparedness is unavailable."], "generatedAt": _now()}
    if phase_two:
        card["decision"].update({"policy": decision_policy_evidence})
        card["assessment"] = {"id": job["assessmentId"], "commitSha256": job["assessmentCommitSha256"],
                              "policy": assessment_policy_evidence, "labelledRows": labelled_rows,
                              "plannedFoldCount": planned_folds, "successfulFolds": candidate["successfulFolds"],
                              "failedFolds": candidate["failedFolds"], "foldPlanSha256": summary["foldPlanSha256"],
                              "selectedEvaluationPeriod": evaluation_period, "recommendationStrength": "not_available"}
        card["authorization"].update({"commitSha256": authorization_commit_sha, "status": "reserved"})
        card["model"].update({"technicalWinnerId": decision["technicalWinnerModelId"],
                              "technicalWinnerParameterHash": decision["technicalWinnerParameterSha256"]})
        card["features"].update({"matrixSha256": feature_matrix_hash})
        card["inputHashes"].update({"authorizationCommit": authorization_commit_sha})
    _update(job_path, job, progress="validating_artifacts")
    _write(artifacts / "model_card.json", card)
    (staging / "logs/events.jsonl").write_text(json.dumps({"timestamp": _now(), "eventType": "approved_forecast_artifacts_ready",
                                                           "runId": job["runId"]}) + "\n", encoding="utf-8")
    _update(job_path, job, status="committing", progress="committing_run")
    committed = commit_approved_forecast(root, staging, job)
    return {"runId": job["runId"], "forecastReported": reported, "latest": committed["pointer"]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--job-record", required=True)
    parser.add_argument("--assessment", required=True)
    parser.add_argument("--staging", required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args), separators=(",", ":")))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "code": "approved_forecast_failed", "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
