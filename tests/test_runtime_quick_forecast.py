import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_policy import load_and_validate_quick_forecast_policy
from runtime_quick_forecast import execute
from runtime_validate import validate
from runtime_active_model import resolve_active_model
from runtime_model_lifecycle import execute as execute_lifecycle
from runtime_active_model import PROFILE_SHA
from tests.test_runtime_model_lifecycle import lifecycle_job


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_ready_runtime(base: Path, row_count: int | None = None):
    runtime = base / "runtime"
    workspace_id, job_id, run_id = (str(uuid.uuid4()) for _ in range(3))
    workspace = runtime / "workspaces" / workspace_id
    for relative in ("metadata", "inputs/original", "inputs/canonical", "logs", "jobs/running", "jobs/pending", "jobs/completed", "jobs/failed", "staging", "runs", "deployments", "locks"):
        (runtime / relative).mkdir(parents=True, exist_ok=True) if not relative.startswith("metadata") and not relative.startswith("inputs") and relative != "logs" else (workspace / relative).mkdir(parents=True, exist_ok=True)
    dengue = workspace / "inputs/original/dengue.csv"
    climate = workspace / "inputs/original/climate.csv"
    shutil.copy2(ROOT / "data/dengue_cases.csv", dengue)
    shutil.copy2(ROOT / "data/climate_data.csv", climate)
    if row_count is not None:
        pd.read_csv(dengue).head(row_count).to_csv(dengue, index=False)
        pd.read_csv(climate).head(row_count).to_csv(climate, index=False)
    created = iso_now()
    result = validate(SimpleNamespace(
        workspace_root=str(workspace), workspace_id=workspace_id, created_at=created,
        dengue_input=str(dengue), climate_input=str(climate),
        canonical_dengue_output=str(workspace / "inputs/canonical/dengue_cases.csv"),
        canonical_climate_output=str(workspace / "inputs/canonical/climate_data.csv"),
        validation_output=str(workspace / "metadata/validation.json"),
        deployment_id="dhaka_south", workflow_mode="quick_forecast",
    ))
    assert result["status"] == "ready" and result["eligibility"]["quickForecast"]["eligible"]
    metadata = {"schemaVersion": "1.0", "workspaceId": workspace_id, "correlationId": str(uuid.uuid4()),
        "deploymentId": "dhaka_south", "workflowMode": "quick_forecast", "status": "ready",
        "createdAt": created, "updatedAt": iso_now(), "originalFiles": {}, "datasetId": result["datasetId"]}
    (workspace / "metadata/workspace.json").write_text(json.dumps(metadata), encoding="utf-8")
    validation_hash = hashlib.sha256((workspace / "metadata/validation.json").read_bytes()).hexdigest()
    policy, policy_hash = load_and_validate_quick_forecast_policy("dhaka_south")
    job = {"schemaVersion": "1.0", "jobId": job_id, "runId": run_id, "workspaceId": workspace_id,
        "datasetId": result["datasetId"], "deploymentId": "dhaka_south", "workflowMode": "quick_forecast",
        "validationRecordSha256": validation_hash, "policyId": policy["policy_id"], "policyVersion": policy["policy_version"],
        "policySha256": policy_hash, "status": "running", "progress": "building_features", "createdAt": created,
        "claimedAt": created, "startedAt": created, "updatedAt": created, "completedAt": None, "heartbeatAt": created,
        "workerId": "test", "processId": None, "timeoutSeconds": 600, "retryCount": 0, "error": None, "committedRunId": None}
    job_path = runtime / "jobs/running" / f"{job_id}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    return runtime, workspace, job_path, job


class RuntimeQuickForecastTests(unittest.TestCase):
    def test_new_quick_execution_rechecks_active_authority_without_changing_model_logic(self):
        source=(ROOT/"analytics/runtime_quick_forecast.py").read_text()
        self.assertIn("resolve_active_model",source)
        self.assertIn("authoritySnapshotSha256",source)
        self.assertIn('model_id"] == "random_forest"',source)
    def test_assignment_aware_profile_fallback_job_executes_with_complete_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime,workspace,job_path,job=build_ready_runtime(Path(directory));authority=resolve_active_model(ROOT,runtime)
            job.update({"activeModelAuthoritySource":authority["authoritySource"],"authoritySnapshotSha256":authority["authoritySnapshotSha256"],"historicalProfileSha256":authority["profileSha256"],"resolvedModelId":authority["modelId"],"resolvedModelFamily":authority["modelFamily"],"resolvedModelParameterSha256":authority["parameterSha256"],"resolvedFeatureOrderSha256":authority["featureOrderSha256"],"resolvedCandidateRegistrySha256":authority["candidateRegistrySha256"],"quickPolicyId":authority["quickPolicyId"],"quickPolicyVersion":authority["quickPolicyVersion"],"quickPolicySha256":authority["quickPolicySha256"]});job_path.write_text(json.dumps(job),encoding="utf-8")
            outcome=execute(SimpleNamespace(runtime_root=str(runtime),job_record=str(job_path),workspace=str(workspace),staging=str(runtime/"staging"/job["runId"])))
            self.assertTrue(outcome["committed"])
    def test_committed_assignment_quick_job_executes_with_complete_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime,workspace,job_path,job=build_ready_runtime(Path(directory))
            lifecycle,lifecycle_path=lifecycle_job(runtime,expectedProfileSha256=PROFILE_SHA)
            execute_lifecycle(lifecycle_path,runtime,runtime/"lifecycle-staging"/lifecycle["lifecycleDecisionId"],ROOT)
            authority=resolve_active_model(ROOT,runtime)
            self.assertEqual(authority["authoritySource"],"committed_assignment")
            job.update({"activeModelAuthoritySource":authority["authoritySource"],"authoritySnapshotSha256":authority["authoritySnapshotSha256"],"assignmentId":authority["assignmentId"],"assignmentCommitSha256":authority["assignmentCommitSha256"],"resolvedModelId":authority["modelId"],"resolvedModelFamily":authority["modelFamily"],"resolvedModelParameterSha256":authority["parameterSha256"],"resolvedFeatureOrderSha256":authority["featureOrderSha256"],"resolvedCandidateRegistrySha256":authority["candidateRegistrySha256"],"quickPolicyId":authority["quickPolicyId"],"quickPolicyVersion":authority["quickPolicyVersion"],"quickPolicySha256":authority["quickPolicySha256"]})
            job_path.write_text(json.dumps(job),encoding="utf-8")
            outcome=execute(SimpleNamespace(runtime_root=str(runtime),job_record=str(job_path),workspace=str(workspace),staging=str(runtime/"staging"/job["runId"])) )
            self.assertTrue(outcome["committed"])
    def test_isolated_point_forecast_commit_has_dataset_calibration_and_no_preparedness(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, workspace, job_path, job = build_ready_runtime(Path(directory))
            outcome = execute(SimpleNamespace(runtime_root=str(runtime), job_record=str(job_path), workspace=str(workspace), staging=str(runtime / "staging" / job["runId"])))
            self.assertTrue(outcome["committed"])
            run = runtime / "runs" / job["runId"]
            forecast = json.loads((run / "artifacts/forecast_output.json").read_text())
            uncertainty = json.loads((run / "artifacts/forecast_uncertainty.json").read_text())
            dashboard = json.loads((run / "artifacts/dashboard_summary.json").read_text())
            card = json.loads((run / "artifacts/model_card.json").read_text())
            calibration = json.loads((run / "artifacts/forecast_calibration.json").read_text())
            pipeline = json.loads((run / "artifacts/pipeline_run_summary.json").read_text())
            commit = json.loads((run / "metadata/commit.json").read_text())
            self.assertEqual(forecast["activeModelId"], "random_forest")
            self.assertEqual(forecast["trainingDataIdentity"]["trainingRowCount"], 173)
            self.assertEqual(uncertainty["uncertaintyStatus"], "available")
            self.assertEqual(calibration["residualCount"], 68)
            self.assertEqual(len(calibration["folds"]), 68)
            self.assertLessEqual(0, uncertainty["lowerRaw"])
            self.assertLessEqual(uncertainty["lowerRaw"], forecast["forecastRaw"])
            self.assertLessEqual(forecast["forecastRaw"], uncertainty["upperRaw"])
            self.assertTrue(pipeline["uncertaintyCalibrationPerformed"])
            self.assertFalse(uncertainty["bundledP13RangeReused"])
            self.assertFalse(uncertainty["rmseFallbackAllowed"])
            self.assertEqual(card["calibration"]["artifactSha256"], commit["artifactHashes"]["forecast_calibration.json"])
            self.assertIsNone(dashboard["preparedness"]["scenarios"])
            self.assertEqual(dashboard["preparedness"]["availabilityStatus"], "unavailable_missing_planning_policy")
            self.assertEqual(dashboard["preparedness"]["facilities"], [])
            self.assertFalse(card["comparisonPerformed"])
            self.assertFalse(card["bestModelClaim"])
            self.assertFalse((run / "artifacts/candidate_model_comparison.json").exists())
            self.assertFalse((run / "artifacts/directives.json").exists())

    def test_insufficient_history_retains_pending_null_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, workspace, job_path, job = build_ready_runtime(Path(directory), row_count=111)
            execute(SimpleNamespace(runtime_root=str(runtime), job_record=str(job_path), workspace=str(workspace), staging=str(runtime / "staging" / job["runId"])))
            run = runtime / "runs" / job["runId"]
            uncertainty = json.loads((run / "artifacts/forecast_uncertainty.json").read_text())
            calibration = json.loads((run / "artifacts/forecast_calibration.json").read_text())
            pipeline = json.loads((run / "artifacts/pipeline_run_summary.json").read_text())
            self.assertEqual(uncertainty["uncertaintyStatus"], "pending_dataset_specific_calibration")
            self.assertTrue(all(uncertainty[key] is None for key in ("lowerRaw", "upperRaw", "lowerReported", "upperReported", "nominalCoverage", "historicalCoverage")))
            self.assertEqual(calibration["residualCount"], 0)
            self.assertEqual(calibration["folds"], [])
            self.assertFalse(pipeline["uncertaintyCalibrationPerformed"])


if __name__ == "__main__":
    unittest.main()
