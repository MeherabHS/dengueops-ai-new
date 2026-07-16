import hashlib
import json
import math
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from feature_engineering import FEATURE_COLUMNS, build_features, build_inference_features
from model_factory import build_candidate_estimator, load_and_validate_candidate_registry
from runtime_commit import atomic_json, sha256_file
from runtime_worker import run_once
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime, iso_now

DEPLOYABLE = ("ridge_regression", "poisson_regression", "random_forest", "gradient_boosting")


class ApprovedForecastTests(unittest.TestCase):
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
                    decision_id, auth_id, job_id, run_id = [str(uuid.uuid4()) for _ in range(4)]
                    created = iso_now()
                    decision_root = runtime / "decisions" / decision_id
                    decision_root.mkdir(parents=True)
                    assessment_commit_hash = sha256_file(assessment / "metadata/commit.json")
                    decision = {
                        "decisionId": decision_id, "assessmentId": assessment_job["assessmentId"],
                        "assessmentCommitSha256": assessment_commit_hash, "datasetId": summary["datasetId"],
                        "deploymentId": "dhaka_south", "validationRecordSha256": summary["provenance"]["validationRecordSha256"],
                        "technicalWinnerModelId": model_id, "decision": "approve_technical_winner",
                        "selectedModelId": model_id, "selectedModelParameterSha256": selected["parametersSha256"],
                        "forecastAuthorized": True, "authorizationId": auth_id,
                    }
                    atomic_json(decision_root / "decision.json", decision)
                    atomic_json(decision_root / "commit.json", {"status": "committed", "decisionId": decision_id})
                    decision_commit_hash = sha256_file(decision_root / "commit.json")
                    auth_root = runtime / "authorizations" / auth_id
                    auth_root.mkdir(parents=True)
                    atomic_json(auth_root / "authorization.json", {"authorizationId": auth_id, "decisionId": decision_id, "decisionCommitSha256": decision_commit_hash})
                    atomic_json(auth_root / "commit.json", {"authorizationSha256": sha256_file(auth_root / "authorization.json")})
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


if __name__ == "__main__":
    unittest.main()
