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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_assessment_commit import RuntimeAssessmentCommitError, commit_runtime_assessment
from runtime_assessment_policy import load_and_validate_assessment_policy
from runtime_validate import validate
from runtime_worker import run_once


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_ready_assessment_runtime(base: Path):
    runtime = (base / "runtime").resolve()
    workspace_id, job_id, assessment_id = (str(uuid.uuid4()) for _ in range(3))
    workspace = runtime / "workspaces" / workspace_id
    for relative in ("metadata", "inputs/original", "inputs/canonical", "logs"):
        (workspace / relative).mkdir(parents=True, exist_ok=True)
    for relative in ("jobs/running", "jobs/pending", "jobs/completed", "jobs/failed", "assessment-staging", "assessments", "staging", "runs", "deployments", "locks"):
        (runtime / relative).mkdir(parents=True, exist_ok=True)
    dengue = workspace / "inputs/original/dengue.csv"
    climate = workspace / "inputs/original/climate.csv"
    shutil.copy2(ROOT / "data/dengue_cases.csv", dengue)
    shutil.copy2(ROOT / "data/climate_data.csv", climate)
    created = iso_now()
    result = validate(SimpleNamespace(workspace_root=str(workspace), workspace_id=workspace_id, created_at=created,
        dengue_input=str(dengue), climate_input=str(climate), canonical_dengue_output=str(workspace / "inputs/canonical/dengue_cases.csv"),
        canonical_climate_output=str(workspace / "inputs/canonical/climate_data.csv"), validation_output=str(workspace / "metadata/validation.json"),
        deployment_id="dhaka_south", workflow_mode="assess_dataset"))
    assert result["eligibility"]["assessDataset"]["assessmentStatus"] == "full_assessment_eligible"
    metadata = {"schemaVersion":"1.0","workspaceId":workspace_id,"correlationId":str(uuid.uuid4()),"deploymentId":"dhaka_south",
        "workflowMode":"assess_dataset","status":"ready","createdAt":created,"updatedAt":iso_now(),"originalFiles":{},"datasetId":result["datasetId"]}
    (workspace / "metadata/workspace.json").write_text(json.dumps(metadata), encoding="utf-8")
    validation_hash = hashlib.sha256((workspace / "metadata/validation.json").read_bytes()).hexdigest()
    policy, policy_hash = load_and_validate_assessment_policy("dhaka_south")
    registry_hash = hashlib.sha256((ROOT / "config/candidate_models.json").read_bytes()).hexdigest()
    job = {"schemaVersion":"1.0","jobKind":"dataset_assessment","jobId":job_id,"assessmentId":assessment_id,"workspaceId":workspace_id,
        "datasetId":result["datasetId"],"deploymentId":"dhaka_south","workflowMode":"assess_dataset","validationRecordSha256":validation_hash,
        "assessmentPolicyId":policy["policy_id"],"assessmentPolicyVersion":policy["policy_version"],"assessmentPolicySha256":policy_hash,
        "candidateRegistrySha256":registry_hash,"status":"queued","progress":"queued","createdAt":created,"claimedAt":None,"startedAt":None,
        "updatedAt":created,"completedAt":None,"heartbeatAt":None,"workerId":None,"processId":None,"timeoutSeconds":1800,"retryCount":0,
        "error":None,"committedAssessmentId":None}
    job_path = runtime / "jobs/pending" / f"{job_id}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    return runtime, workspace, job_path, job


class RuntimeAssessmentCommitTests(unittest.TestCase):
    def test_worker_commits_direct_seven_candidate_assessment_without_latest(self):
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        with tempfile.TemporaryDirectory() as directory:
            runtime, _workspace, pending, job = build_ready_assessment_runtime(Path(directory))
            self.assertTrue(run_once(runtime, "assessment-test-worker"))
            completed = runtime / "jobs/completed" / pending.name
            failed = runtime / "jobs/failed" / pending.name
            diagnostics = failed.read_text(errors="replace") if failed.exists() else ""
            for path in runtime.glob("assessment-staging*/**/stderr.log"):
                diagnostics += path.read_text(errors="replace")
            self.assertTrue(completed.exists(), diagnostics)
            completed_job = json.loads(completed.read_text())
            self.assertEqual(completed_job["committedAssessmentId"], job["assessmentId"])
            committed = runtime / "assessments" / job["assessmentId"]
            rolling = json.loads((committed / "artifacts/rolling_validation.json").read_text())
            comparison = json.loads((committed / "artifacts/candidate_model_comparison.json").read_text())
            recommendation = json.loads((committed / "artifacts/recommendation.json").read_text())
            self.assertEqual(len(rolling["folds"]), 68)
            self.assertTrue(all(len(fold["predictions"]) == 7 for fold in rolling["folds"]))
            self.assertEqual({fold["featureOrderSha256"] for fold in rolling["folds"]}, {rolling["featureOrderSha256"]})
            gbr = next(value for value in comparison["candidates"] if value["modelId"] == "gradient_boosting")
            self.assertEqual(gbr["executionMode"], "fitted_per_fold")
            self.assertFalse(gbr["historicalPredictionsReused"])
            self.assertEqual(recommendation["recommendationStatus"], "evidence_only")
            self.assertEqual(recommendation["recommendationStrength"], "not_available")
            self.assertFalse(recommendation["approvalEnabled"])
            self.assertFalse((runtime / "deployments/dhaka_south/latest.json").exists())
            for prohibited in ("forecast_output.json","forecast_uncertainty.json","model_card.json","dashboard_summary.json","directives.json"):
                self.assertFalse((committed / "artifacts" / prohibited).exists())
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_incomplete_bundle_cannot_commit_or_create_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            assessment_id = str(uuid.uuid4())
            staging = root / "assessment-staging" / assessment_id
            (staging / "artifacts").mkdir(parents=True)
            job = {"assessmentId":assessment_id,"jobId":str(uuid.uuid4()),"workspaceId":str(uuid.uuid4()),"datasetId":"a"*64,
                "deploymentId":"dhaka_south","validationRecordSha256":"b"*64,"assessmentPolicySha256":"c"*64,"candidateRegistrySha256":"d"*64}
            with self.assertRaises(RuntimeAssessmentCommitError):
                commit_runtime_assessment(root, staging, job)
            self.assertFalse((root / "deployments/dhaka_south/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
