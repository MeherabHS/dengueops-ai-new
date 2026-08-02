from __future__ import annotations

import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

import runtime_worker
import runtime_assessment_commit
from runtime_assessment_commit import RuntimeAssessmentCommitError


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def assessment_job() -> dict[str, object]:
    return {
        "jobKind": "dataset_assessment",
        "jobId": str(uuid.uuid4()),
        "workspaceId": str(uuid.uuid4()),
        "assessmentId": str(uuid.uuid4()),
        "datasetId": "a" * 64,
        "deploymentId": "dhaka_south",
        "assessmentPolicyVersion": "p2-v3",
        "updatedAt": timestamp(),
    }


class RuntimeAssessmentLockingTests(unittest.TestCase):
    def committed_fixture(self, root: Path, job: dict[str, object]) -> Path:
        committed = root / "assessments" / str(job["assessmentId"])
        (committed / "artifacts").mkdir(parents=True)
        (committed / "metadata").mkdir()
        for name in runtime_assessment_commit.REQUIRED_ARTIFACTS:
            (committed / "artifacts" / name).write_text("fixture", encoding="utf-8")
        return committed

    def test_worker_releases_global_lock_before_assessment_child_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime_worker.ensure_structure(root)
            path = root / "jobs/running/job.json"
            job = assessment_job()

            def execute(_root, _path, _worker):
                self.assertFalse((root / "locks/analytics.lock").exists())

            with patch.object(runtime_worker, "claim_one", return_value=path), \
                    patch.object(runtime_worker, "load_job", return_value=job), \
                    patch.object(runtime_worker, "execute_claimed", side_effect=execute):
                self.assertTrue(runtime_worker.run_once(root, "test-worker"))
            self.assertFalse((root / "locks/analytics.lock").exists())

    def test_assessment_lock_is_released_when_child_execution_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime_worker.ensure_structure(root)
            path = root / "jobs/running/job.json"
            with patch.object(runtime_worker, "claim_one", return_value=path), \
                    patch.object(runtime_worker, "load_job", return_value=assessment_job()), \
                    patch.object(runtime_worker, "execute_claimed", side_effect=RuntimeError("failure")):
                self.assertTrue(runtime_worker.run_once(root, "test-worker"))
            self.assertFalse((root / "locks/analytics.lock").exists())

    def test_verified_committed_assessment_recovers_without_subprocess(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime_worker.ensure_structure(root)
            job = assessment_job()
            workspace = root / "workspaces" / str(job["workspaceId"])
            workspace.mkdir(parents=True)
            committed = root / "assessments" / str(job["assessmentId"])
            committed.mkdir(parents=True)
            path = root / "jobs/running/job.json"
            path.write_text("{}", encoding="utf-8")
            with patch.object(runtime_worker, "load_job", return_value=job), \
                    patch.object(runtime_worker, "verify_committed_runtime_assessment") as verify, \
                    patch.object(runtime_worker, "finalize_job") as finalize, \
                    patch.object(runtime_worker.subprocess, "Popen") as popen:
                runtime_worker.execute_claimed(root, path, "test-worker")
            verify.assert_called_once_with(root, committed, job)
            finalize.assert_called_once()
            self.assertEqual(finalize.call_args.kwargs["committedAssessmentId"], job["assessmentId"])
            popen.assert_not_called()

    def test_startup_reconciles_matching_committed_assessment(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime_worker.ensure_structure(root)
            job = assessment_job()
            path = root / "jobs/running/job.json"
            path.write_text("{}", encoding="utf-8")
            committed = root / "assessments" / str(job["assessmentId"])
            committed.mkdir(parents=True)
            with patch.object(runtime_worker, "load_job", return_value=job), \
                    patch.object(runtime_worker, "verify_committed_runtime_assessment") as verify, \
                    patch.object(runtime_worker, "finalize_job") as finalize:
                runtime_worker.recover_stale_jobs(root)
            verify.assert_called_once_with(root, committed, job)
            finalize.assert_called_once()
            self.assertEqual(finalize.call_args.kwargs["status"], "completed")

    def test_timed_out_job_with_verified_commit_recovers_without_refit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime_worker.ensure_structure(root)
            job = {**assessment_job(), "status": "timed_out", "progress": "timed_out",
                   "error": {"code": "assessment_timeout", "message": "timeout", "retryable": True}}
            failed = root / "jobs/failed/job.json"
            failed.write_text("{}", encoding="utf-8")
            committed = root / "assessments" / str(job["assessmentId"])
            committed.mkdir(parents=True)
            with patch.object(runtime_worker, "load_job", return_value=job), \
                    patch.object(runtime_worker, "verify_committed_runtime_assessment") as verify, \
                    patch.object(runtime_worker, "atomic_json") as write, \
                    patch.object(runtime_worker.os, "replace") as replace, \
                    patch.object(runtime_worker.subprocess, "Popen") as popen:
                runtime_worker.recover_stale_jobs(root)
            verify.assert_called_once_with(root, committed, job)
            write.assert_called_once()
            recovered = write.call_args.args[1]
            self.assertEqual(recovered["status"], "completed")
            self.assertEqual(recovered["committedAssessmentId"], job["assessmentId"])
            self.assertIsNone(recovered["error"])
            replace.assert_called_once_with(failed, root / "jobs/completed/job.json")
            popen.assert_not_called()

    def test_tampered_committed_assessment_is_not_reconciled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime_worker.ensure_structure(root)
            job = assessment_job()
            path = root / "jobs/running/job.json"
            path.write_text("{}", encoding="utf-8")
            (root / "assessments" / str(job["assessmentId"])).mkdir(parents=True)
            with patch.object(runtime_worker, "load_job", return_value=job), \
                    patch.object(runtime_worker, "verify_committed_runtime_assessment", side_effect=RuntimeAssessmentCommitError("tampered")), \
                    patch.object(runtime_worker, "finalize_job") as finalize:
                runtime_worker.recover_stale_jobs(root)
            finalize.assert_not_called()

    def test_committed_verifier_rejects_incomplete_and_tampered_bundles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            job = assessment_job()
            committed = self.committed_fixture(root, job)
            identity = {
                field: job[field]
                for field in ("assessmentId", "jobId", "workspaceId", "datasetId", "deploymentId")
            }
            artifact_identity = {
                field: job[field]
                for field in ("assessmentId", "jobId", "datasetId", "deploymentId")
            }
            hashes = {name: "a" * 64 for name in runtime_assessment_commit.REQUIRED_ARTIFACTS}
            commit = {**identity, "status": "committed", "latestPointerUpdated": False,
                      "committedAt": "2026-08-02T06:14:41Z", "artifactHashes": hashes}
            assessment = {**artifact_identity, "artifactHashes": {
                "inputManifestSha256": hashes["input_manifest.json"],
                "modelFeaturesSha256": hashes["model_features.csv"],
                "rollingValidationSha256": hashes["rolling_validation.json"],
                "candidateComparisonSha256": hashes["candidate_model_comparison.json"],
                "recommendationSha256": hashes["recommendation.json"],
                "assessmentSummarySha256": hashes["assessment_summary.json"],
            }}
            summary = {**artifact_identity, "committedAt": commit["committedAt"]}

            def validated(path: Path, _schema: str):
                if path.name == "commit.json":
                    return commit
                if path.name == "assessment.json":
                    return assessment
                if path.name == "assessment_summary.json":
                    return summary
                return artifact_identity

            with patch.object(runtime_assessment_commit, "_validate", side_effect=validated), \
                    patch.object(runtime_assessment_commit, "sha256_file", return_value="a" * 64):
                runtime_assessment_commit.verify_committed_runtime_assessment(root, committed, job)
                missing = committed / "artifacts/input_manifest.json"
                missing.unlink()
                with self.assertRaises(RuntimeAssessmentCommitError):
                    runtime_assessment_commit.verify_committed_runtime_assessment(root, committed, job)
                missing.write_text("fixture", encoding="utf-8")

            def tampered_hash(path: Path) -> str:
                return "b" * 64 if path.name == "model_features.csv" else "a" * 64

            with patch.object(runtime_assessment_commit, "_validate", side_effect=validated), \
                    patch.object(runtime_assessment_commit, "sha256_file", side_effect=tampered_hash):
                with self.assertRaises(RuntimeAssessmentCommitError):
                    runtime_assessment_commit.verify_committed_runtime_assessment(root, committed, job)

    def test_monitoring_failure_cannot_reverse_completed_assessment(self):
        job = assessment_job()
        with patch("runtime_governed_monitoring.publish_current_monitoring", side_effect=RuntimeError("monitoring failed")) as publish:
            runtime_worker.dispatch_downstream(Path("C:/runtime"), job)
        publish.assert_called_once()


if __name__ == "__main__":
    unittest.main()
