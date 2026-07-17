import hashlib
import json
import math
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from feature_engineering import FEATURE_COLUMNS, build_features, build_inference_features
from model_factory import build_candidate_estimator, load_and_validate_candidate_registry
from runtime_commit import atomic_json, sha256_file
from runtime_worker import run_once
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime, iso_now
from runtime_forecast_outcome import execute as execute_outcome
from runtime_forecast_outcome_source import ForecastSourceError,verify_forecast_source
from tests.test_runtime_forecast_outcome import build_outcome_job
from runtime_model_degradation_evidence import execute as execute_degradation
from tests.test_runtime_model_degradation_evidence import degradation_job
from types import SimpleNamespace

DEPLOYABLE = ("ridge_regression", "poisson_regression", "random_forest", "gradient_boosting")


class ApprovedForecastTests(unittest.TestCase):
    def test_phase_two_full_training_rows_are_independent_of_capped_fold_count(self):
        cases = pd.read_csv(ROOT / "data/dengue_cases.csv")
        climate = pd.read_csv(ROOT / "data/climate_data.csv")
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for source_rows, expected_training, expected_folds in ((164, 157, 52), (165, 158, 53), (180, 173, 68)):
                case_path, climate_path = target / f"cases-{source_rows}.csv", target / f"climate-{source_rows}.csv"
                cases.iloc[:source_rows].to_csv(case_path, index=False)
                climate.iloc[:source_rows].to_csv(climate_path, index=False)
                training, _ = build_features(case_path, climate_path, output_path=None)
                self.assertEqual((len(training), min(len(training) - 105, 68)), (expected_training, expected_folds))
            extended_cases, extended_climate = cases.copy(), climate.copy()
            for offset in range(1, 11):
                case_row, climate_row = cases.iloc[-1].copy(), climate.iloc[-1].copy()
                case_row["epi_week"] = 24 + offset
                climate_row["epi_week"] = 24 + offset
                date = (pd.Timestamp("2024-06-10") + pd.Timedelta(weeks=offset)).strftime("%Y-%m-%d")
                case_row["date_start"] = climate_row["date_start"] = date
                extended_cases.loc[len(extended_cases)] = case_row
                extended_climate.loc[len(extended_climate)] = climate_row
            case_path, climate_path = target / "cases-capped.csv", target / "climate-capped.csv"
            extended_cases.to_csv(case_path, index=False)
            extended_climate.to_csv(climate_path, index=False)
            training, _ = build_features(case_path, climate_path, output_path=None)
            self.assertEqual(len(training), 183)
            self.assertEqual(min(len(training) - 105, 68), 68)

    def test_all_deployable_candidates_fit_full_data_with_exact_hashes(self):
        registry, _ = load_and_validate_candidate_registry()
        training, _ = build_features(ROOT / "data/dengue_cases.csv", ROOT / "data/climate_data.csv", output_path=None)
        inference = build_inference_features(ROOT / "data/dengue_cases.csv", ROOT / "data/climate_data.csv")
        self.assertEqual(len(training), 173)
        X = training[FEATURE_COLUMNS]
        y = training["target_cases_next_2w"]
        x = inference.iloc[-1][FEATURE_COLUMNS].to_frame().T
        for model_id in DEPLOYABLE:
            with self.subTest(model=model_id):
                candidate = next(candidate for candidate in registry["candidates"] if candidate["model_id"] == model_id)
                model = build_candidate_estimator(model_id, registry)
                model.fit(X, y)
                prediction = float(model.predict(x)[0])
                self.assertTrue(math.isfinite(prediction))
                self.assertEqual(candidate["parameters_sha256"], hashlib.sha256(json.dumps(candidate["parameters"], sort_keys=True, separators=(",", ":")).encode()).hexdigest())

    def test_each_deployable_selected_model_completes_one_authorized_point_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            base_runtime, _workspace, _pending, assessment_job = build_ready_assessment_runtime(Path(directory) / "base")
            self.assertTrue(run_once(base_runtime, "assessment-worker"))
            base_assessment = base_runtime / "assessments" / assessment_job["assessmentId"]
            base_summary = json.loads((base_assessment / "artifacts/assessment_summary.json").read_text())
            for model_id in DEPLOYABLE:
                with self.subTest(model=model_id):
                    runtime = (Path(directory) / model_id / "runtime").resolve()
                    shutil.copytree(base_runtime, runtime, copy_function=shutil.copyfile)
                    assessment = runtime / "assessments" / assessment_job["assessmentId"]
                    summary = json.loads((assessment / "artifacts/assessment_summary.json").read_text())
                    selected = next(candidate for candidate in summary["candidates"] if candidate["modelId"] == model_id)
                    self.assertTrue(selected["selectionEligible"])
                    comparison_path = assessment / "artifacts/candidate_model_comparison.json"
                    summary_path = assessment / "artifacts/assessment_summary.json"
                    comparison = json.loads(comparison_path.read_text())
                    comparison["technicalWinnerModelId"] = model_id
                    summary["technicalWinnerModelId"] = model_id
                    atomic_json(comparison_path, comparison)
                    summary["evidenceHashes"]["candidateComparisonSha256"] = sha256_file(comparison_path)
                    atomic_json(summary_path, summary)
                    assessment_commit_path = assessment / "metadata/commit.json"
                    assessment_commit = json.loads(assessment_commit_path.read_text())
                    assessment_commit["artifactHashes"]["candidate_model_comparison.json"] = sha256_file(comparison_path)
                    assessment_commit["artifactHashes"]["assessment_summary.json"] = sha256_file(summary_path)
                    atomic_json(assessment_commit_path, assessment_commit)
                    decision_id, auth_id, job_id, run_id = [str(uuid.uuid4()) for _ in range(4)]
                    created = iso_now()
                    expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
                    decision_root = runtime / "decisions" / decision_id
                    decision_root.mkdir(parents=True)
                    assessment_commit_hash = sha256_file(assessment_commit_path)
                    policy = json.loads((ROOT / "config/deployments/dhaka_south/decision_policy.json").read_text())
                    decision = {
                        "schemaVersion": "2.0",
                        "decisionId": decision_id, "assessmentId": assessment_job["assessmentId"],
                        "assessmentCommitSha256": assessment_commit_hash, "datasetId": summary["datasetId"],
                        "assessmentSchemaVersion": "2.0", "assessmentLabelledRows": summary["labelledRows"],
                        "assessmentPlannedFoldCount": summary["foldPolicy"]["plannedFoldCount"],
                        "selectedEvaluationPeriod": summary["foldPolicy"]["selectedEvaluationPeriod"],
                        "assessmentSummarySha256": sha256_file(summary_path),
                        "comparisonSha256": sha256_file(comparison_path),
                        "recommendationSha256": summary["evidenceHashes"]["recommendationSha256"],
                        "foldPlanSha256": summary["foldPlanSha256"],
                        "deploymentId": "dhaka_south", "validationRecordSha256": summary["provenance"]["validationRecordSha256"],
                        "assessmentPolicyId": policy["allowedAssessmentPolicyId"],
                        "assessmentPolicyVersion": policy["allowedAssessmentPolicyVersion"],
                        "assessmentPolicySha256": policy["allowedAssessmentPolicySha256"],
                        "decisionPolicyId": policy["policyId"], "decisionPolicyVersion": policy["policyVersion"],
                        "decisionPolicySha256": policy["policySha256"], "candidateRegistrySha256": policy["candidateRegistrySha256"],
                        "technicalWinnerModelId": model_id, "decision": "approve_technical_winner",
                        "technicalWinnerParameterSha256": selected["parametersSha256"],
                        "selectedModelId": model_id, "selectedModelParameterSha256": selected["parametersSha256"],
                        "decisionScope": "one_run", "operatorType": "trusted_internal_unverified",
                        "operatorIdentifier": "test-operator", "institutionalApproval": False, "reason": "Governed test decision.",
                        "limitationsAcknowledged": True, "decisionStatus": "approved_technical_winner",
                        "forecastAuthorized": True, "authorizationId": auth_id, "createdAt": created,
                        "correlationId": str(uuid.uuid4()), "supersedesDecisionId": None, "supersessionStatus": "active",
                    }
                    atomic_json(decision_root / "decision.json", decision)
                    decision_commit = {"schemaVersion": "2.0", "decisionId": decision_id,
                        "assessmentId": assessment_job["assessmentId"], "decisionSha256": sha256_file(decision_root / "decision.json"),
                        "assessmentCommitSha256": assessment_commit_hash, "assessmentSchemaVersion": "2.0",
                        "assessmentSummarySha256": sha256_file(summary_path), "assessmentPolicyId": policy["allowedAssessmentPolicyId"],
                        "assessmentPolicyVersion": policy["allowedAssessmentPolicyVersion"],
                        "assessmentPolicySha256": policy["allowedAssessmentPolicySha256"], "decisionPolicyId": policy["policyId"],
                        "decisionPolicyVersion": policy["policyVersion"], "decisionPolicySha256": policy["policySha256"],
                        "foldPlanSha256": summary["foldPlanSha256"], "assessmentLabelledRows": summary["labelledRows"],
                        "assessmentPlannedFoldCount": summary["foldPolicy"]["plannedFoldCount"], "status": "committed",
                        "committedAt": created, "latestPointerUpdated": False, "deploymentProfileModified": False}
                    atomic_json(decision_root / "commit.json", decision_commit)
                    decision_commit_hash = sha256_file(decision_root / "commit.json")
                    auth_root = runtime / "authorizations" / auth_id
                    auth_root.mkdir(parents=True)
                    authorization = {"schemaVersion": "2.0", "authorizationId": auth_id, "decisionId": decision_id,
                        "decisionCommitSha256": decision_commit_hash, "assessmentId": assessment_job["assessmentId"],
                        "assessmentCommitSha256": assessment_commit_hash, "assessmentPolicyId": policy["allowedAssessmentPolicyId"],
                        "assessmentPolicyVersion": policy["allowedAssessmentPolicyVersion"],
                        "assessmentPolicySha256": policy["allowedAssessmentPolicySha256"], "decisionPolicyId": policy["policyId"],
                        "decisionPolicyVersion": policy["policyVersion"], "decisionPolicySha256": policy["policySha256"],
                        "datasetId": summary["datasetId"], "deploymentId": "dhaka_south", "selectedModelId": model_id,
                        "selectedModelParameterSha256": selected["parametersSha256"], "assessmentLabelledRows": summary["labelledRows"],
                        "assessmentPlannedFoldCount": summary["foldPolicy"]["plannedFoldCount"],
                        "foldPlanSha256": summary["foldPlanSha256"], "workflowMode": "approved_assessment_forecast",
                        "scope": "one_run", "initialStatus": "available", "createdAt": created, "expiresAt": expires,
                        "policyId": policy["policyId"], "policyVersion": policy["policyVersion"], "policySha256": policy["policySha256"]}
                    atomic_json(auth_root / "authorization.json", authorization)
                    atomic_json(auth_root / "commit.json", {"schemaVersion": "1.0", "authorizationId": auth_id,
                        "decisionId": decision_id, "authorizationSha256": sha256_file(auth_root / "authorization.json"),
                        "decisionCommitSha256": decision_commit_hash, "status": "committed", "committedAt": created})
                    state = runtime / "authorization-state" / auth_id
                    state.mkdir(parents=True)
                    atomic_json(state / "reservation.json", {"schemaVersion": "1.0", "authorizationId": auth_id, "decisionId": decision_id, "eventType": "reserved", "eventId": str(uuid.uuid4()), "createdAt": created, "jobId": job_id, "runId": run_id})
                    job = {
                        "schemaVersion": "1.0", "jobKind": "approved_forecast", "jobId": job_id, "runId": run_id,
                        "decisionId": decision_id, "decisionCommitSha256": decision_commit_hash, "authorizationId": auth_id,
                        "assessmentId": assessment_job["assessmentId"], "assessmentCommitSha256": assessment_commit_hash,
                        "workspaceId": assessment_job["assessmentId"], "datasetId": summary["datasetId"], "deploymentId": "dhaka_south",
                        "selectedModelId": model_id, "selectedModelParameterSha256": selected["parametersSha256"],
                        "workflowMode": "approved_assessment_forecast", "validationRecordSha256": summary["provenance"]["validationRecordSha256"],
                        "status": "queued", "progress": "queued", "createdAt": created, "claimedAt": None, "startedAt": None,
                        "updatedAt": created, "completedAt": None, "heartbeatAt": None, "workerId": None, "processId": None,
                        "timeoutSeconds": 600, "retryCount": 0, "error": None, "committedRunId": None,
                    }
                    atomic_json(runtime / "jobs/pending" / f"{job_id}.json", job)
                    self.assertTrue(run_once(runtime, f"approved-{model_id}"))
                    completed = json.loads((runtime / "jobs/completed" / f"{job_id}.json").read_text())
                    self.assertEqual(completed["committedRunId"], run_id)
                    run = runtime / "runs" / run_id
                    output = json.loads((run / "artifacts/forecast_output.json").read_text())
                    uncertainty = json.loads((run / "artifacts/forecast_uncertainty.json").read_text())
                    dashboard = json.loads((run / "artifacts/dashboard_summary.json").read_text())
                    card = json.loads((run / "artifacts/model_card.json").read_text())
                    self.assertEqual(output["selectedModelId"], model_id)
                    self.assertEqual(output["selectedModelParameterSha256"], selected["parametersSha256"])
                    self.assertEqual(output["trainingDataIdentity"]["trainingRowCount"], 173)
                    self.assertTrue(math.isfinite(output["forecastRaw"]))
                    self.assertFalse(output["deploymentModelAdopted"])
                    self.assertEqual(card["model"]["candidateRegistrySha256"], base_summary["provenance"]["candidateRegistrySha256"])
                    self.assertEqual(uncertainty["uncertaintyStatus"], "pending_selected_model_calibration")
                    self.assertIsNone(uncertainty["lowerRaw"])
                    self.assertEqual(dashboard["preparedness"]["availabilityStatus"], "unavailable_missing_planning_policy")
                    self.assertFalse((run / "artifacts/candidate_model_comparison.json").exists())
                    self.assertFalse((run / "artifacts/directives.json").exists())
                    self.assertTrue((state / "consumption.json").exists())
                    pointer = json.loads((runtime / "deployments/dhaka_south/latest.json").read_text())
                    self.assertEqual(pointer["runId"], run_id)
                    self.assertEqual(pointer["selectedModelId"], model_id)
                    outcome_job,outcome_path=build_outcome_job(runtime,{"runId":run_id},record_id=f"approved-{model_id}")
                    execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(outcome_path),staging=str(runtime/"outcome-staging"/outcome_job["outcomeId"])))
                    outcome=json.loads((runtime/"forecast-outcomes"/outcome_job["outcomeId"]/"artifacts/outcome_evaluation.json").read_text())
                    self.assertEqual((outcome["sourceFamily"],outcome["modelId"]),("approved_forecast_p2",model_id))
                    self.assertEqual(outcome["sourceEvidence"]["trainingRowCount"],173)
                    self.assertEqual(outcome["sourceEvidence"]["plannedFoldCount"],68)
                    self.assertEqual(outcome["empiricalRangeStatus"],"pending_selected_model_calibration")
                    degradation,degradation_path=degradation_job(runtime)
                    execute_degradation(SimpleNamespace(runtime_root=str(runtime),job_record=str(degradation_path),staging=str(runtime/"degradation-staging"/degradation["evidenceId"])))
                    degradation_value=json.loads((runtime/"degradation-evidence"/degradation["evidenceId"]/"artifacts/degradation_evidence.json").read_text())
                    reference=degradation_value["cohorts"][0]["assessmentReferences"][0]
                    self.assertEqual((reference["modelId"],reference["parameterSha256"]),(model_id,selected["parametersSha256"]))
                    self.assertEqual(reference["comparabilityStatus"],"limited_cross_population_comparability")
                    self.assertEqual(degradation_value["cohorts"][0]["monitoringWindow"]["status"],"window_size_not_governed")
                    if model_id=="random_forest":
                        source_commit=sha256_file(run/"metadata/commit.json")
                        for tampered in (run/"artifacts/forecast_output.json",runtime/"assessments"/assessment_job["assessmentId"]/"metadata/commit.json",decision_root/"commit.json",auth_root/"commit.json"):
                            original=tampered.read_bytes();tampered.write_bytes(original+b"\n")
                            with self.assertRaises(ForecastSourceError):verify_forecast_source(runtime,run_id,source_commit,{"approved_forecast_p2"})
                            tampered.write_bytes(original)

    def test_phase_one_approved_forecast_remains_schema_one_with_exact_history(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _workspace, _pending, assessment_job = build_ready_assessment_runtime(
                Path(directory), assessment_policy_version="p1.4d-1-v1"
            )
            self.assertTrue(run_once(runtime, "phase-one-assessment"))
            assessment = runtime / "assessments" / assessment_job["assessmentId"]
            summary_path = assessment / "artifacts/assessment_summary.json"
            comparison_path = assessment / "artifacts/candidate_model_comparison.json"
            summary = json.loads(summary_path.read_text())
            selected = next(value for value in summary["candidates"] if value["modelId"] == "random_forest")
            winner = next((value for value in summary["candidates"] if value["modelId"] == summary["technicalWinnerModelId"]), None)
            policy = json.loads((ROOT / "config/deployments/dhaka_south/decision_policy_p1.4d-3-e-v1.json").read_text())
            decision_id, auth_id, job_id, run_id = [str(uuid.uuid4()) for _ in range(4)]
            created = iso_now()
            expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            assessment_commit_hash = sha256_file(assessment / "metadata/commit.json")
            decision_root = runtime / "decisions" / decision_id
            decision_root.mkdir(parents=True)
            decision = {"schemaVersion": "1.0", "decisionId": decision_id, "assessmentId": assessment_job["assessmentId"],
                "assessmentCommitSha256": assessment_commit_hash, "assessmentSummarySha256": sha256_file(summary_path),
                "comparisonSha256": sha256_file(comparison_path), "recommendationSha256": summary["evidenceHashes"]["recommendationSha256"],
                "foldPlanSha256": summary["foldPlanSha256"], "datasetId": summary["datasetId"], "deploymentId": "dhaka_south",
                "validationRecordSha256": summary["provenance"]["validationRecordSha256"],
                "assessmentPolicyId": policy["allowedAssessmentPolicyId"], "assessmentPolicyVersion": policy["allowedAssessmentPolicyVersion"],
                "assessmentPolicySha256": policy["allowedAssessmentPolicySha256"], "decisionPolicyId": policy["policyId"],
                "decisionPolicyVersion": policy["policyVersion"], "decisionPolicySha256": policy["policySha256"],
                "candidateRegistrySha256": policy["candidateRegistrySha256"], "technicalWinnerModelId": summary["technicalWinnerModelId"],
                "technicalWinnerParameterSha256": (winner or {}).get("parametersSha256"), "decision": "keep_current_model",
                "selectedModelId": "random_forest", "selectedModelParameterSha256": selected["parametersSha256"],
                "decisionScope": "one_run", "operatorType": "trusted_internal_unverified", "operatorIdentifier": "test-operator",
                "institutionalApproval": False, "reason": "Historical compatibility test.", "limitationsAcknowledged": True,
                "decisionStatus": "current_model_retained", "forecastAuthorized": True, "authorizationId": auth_id,
                "createdAt": created, "correlationId": str(uuid.uuid4()), "supersedesDecisionId": None, "supersessionStatus": "active"}
            atomic_json(decision_root / "decision.json", decision)
            atomic_json(decision_root / "commit.json", {"schemaVersion": "1.0", "decisionId": decision_id,
                "assessmentId": assessment_job["assessmentId"], "decisionSha256": sha256_file(decision_root / "decision.json"),
                "assessmentCommitSha256": assessment_commit_hash, "decisionPolicySha256": policy["policySha256"],
                "status": "committed", "committedAt": created, "latestPointerUpdated": False, "deploymentProfileModified": False})
            decision_commit_hash = sha256_file(decision_root / "commit.json")
            auth_root = runtime / "authorizations" / auth_id
            auth_root.mkdir(parents=True)
            atomic_json(auth_root / "authorization.json", {"schemaVersion": "1.0", "authorizationId": auth_id,
                "decisionId": decision_id, "decisionCommitSha256": decision_commit_hash, "assessmentId": assessment_job["assessmentId"],
                "assessmentCommitSha256": assessment_commit_hash, "datasetId": summary["datasetId"], "deploymentId": "dhaka_south",
                "selectedModelId": "random_forest", "selectedModelParameterSha256": selected["parametersSha256"],
                "workflowMode": "approved_assessment_forecast", "scope": "one_run", "initialStatus": "available",
                "createdAt": created, "expiresAt": expires, "policyId": policy["policyId"], "policyVersion": policy["policyVersion"],
                "policySha256": policy["policySha256"]})
            atomic_json(auth_root / "commit.json", {"schemaVersion": "1.0", "authorizationId": auth_id,
                "decisionId": decision_id, "authorizationSha256": sha256_file(auth_root / "authorization.json"),
                "decisionCommitSha256": decision_commit_hash, "status": "committed", "committedAt": created})
            state = runtime / "authorization-state" / auth_id
            state.mkdir(parents=True)
            atomic_json(state / "reservation.json", {"schemaVersion": "1.0", "authorizationId": auth_id,
                "decisionId": decision_id, "eventType": "reserved", "eventId": str(uuid.uuid4()), "createdAt": created,
                "jobId": job_id, "runId": run_id})
            job = {"schemaVersion": "1.0", "jobKind": "approved_forecast", "jobId": job_id, "runId": run_id,
                "decisionId": decision_id, "decisionCommitSha256": decision_commit_hash, "authorizationId": auth_id,
                "assessmentId": assessment_job["assessmentId"], "assessmentCommitSha256": assessment_commit_hash,
                "workspaceId": assessment_job["assessmentId"], "datasetId": summary["datasetId"], "deploymentId": "dhaka_south",
                "selectedModelId": "random_forest", "selectedModelParameterSha256": selected["parametersSha256"],
                "workflowMode": "approved_assessment_forecast", "validationRecordSha256": summary["provenance"]["validationRecordSha256"],
                "status": "queued", "progress": "queued", "createdAt": created, "claimedAt": None, "startedAt": None,
                "updatedAt": created, "completedAt": None, "heartbeatAt": None, "workerId": None, "processId": None,
                "timeoutSeconds": 600, "retryCount": 0, "error": None, "committedRunId": None}
            atomic_json(runtime / "jobs/pending" / f"{job_id}.json", job)
            self.assertTrue(run_once(runtime, "phase-one-approved"))
            output = json.loads((runtime / "runs" / run_id / "artifacts/forecast_output.json").read_text())
            commit = json.loads((runtime / "runs" / run_id / "metadata/commit.json").read_text())
            self.assertEqual((output["schemaVersion"], commit["schemaVersion"]), ("1.0", "1.0"))
            self.assertEqual(output["trainingDataIdentity"]["trainingRowCount"], 173)
            self.assertNotIn("governanceEvidence", output)
            outcome_job,outcome_path=build_outcome_job(runtime,{"runId":run_id},record_id="approved-phase-one")
            execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(outcome_path),staging=str(runtime/"outcome-staging"/outcome_job["outcomeId"])))
            outcome=json.loads((runtime/"forecast-outcomes"/outcome_job["outcomeId"]/"artifacts/outcome_evaluation.json").read_text())
            self.assertEqual(outcome["sourceFamily"],"approved_forecast_p1")
            self.assertEqual((outcome["sourceEvidence"]["trainingRowCount"],outcome["sourceEvidence"]["plannedFoldCount"]),(173,68))
            degradation,degradation_path=degradation_job(runtime)
            execute_degradation(SimpleNamespace(runtime_root=str(runtime),job_record=str(degradation_path),staging=str(runtime/"degradation-staging"/degradation["evidenceId"])))
            degradation_value=json.loads((runtime/"degradation-evidence"/degradation["evidenceId"]/"artifacts/degradation_evidence.json").read_text())
            self.assertEqual(degradation_value["cohorts"][0]["assessmentReferences"][0]["plannedFoldCount"],68)


if __name__ == "__main__":
    unittest.main()
