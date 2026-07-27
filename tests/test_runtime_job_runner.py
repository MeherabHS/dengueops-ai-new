import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))
from runtime_worker import claim_one, ensure_structure, load_job, run_once
from tests.test_runtime_forecast_outcome import build_outcome_job
from runtime_forecast_outcome import execute as execute_outcome
from tests.test_runtime_model_degradation_evidence import degradation_job
from tests.test_runtime_quick_forecast import build_ready_runtime, execute_historical_quick_forecast
from tests.test_product_v2_quick_forecast import (
    _create_p2_v2_assignment,
    _setup_quick_run_job,
    build_ready_workspace,
)


def build_pending_governed_quick_job(base: Path, schema_version: str = "2.1", model_id: str = "ridge_regression"):
    root = Path(_create_p2_v2_assignment(base, ROOT, model_id=model_id))
    workspace, dataset_id, validation_sha = build_ready_workspace(root)
    job, running_path, staging = _setup_quick_run_job(
        root, workspace.name, dataset_id, validation_sha
    )
    job.update(
        schemaVersion=schema_version,
        status="queued",
        progress="queued",
        claimedAt=None,
        startedAt=None,
        completedAt=None,
        heartbeatAt=None,
        workerId=None,
        processId=None,
        timeoutSeconds=600,
        retryCount=0,
        error=None,
        committedRunId=None,
    )
    staging.rmdir()
    pending = root / "jobs/pending" / running_path.name
    pending.parent.mkdir(parents=True, exist_ok=True)
    pending.write_text(json.dumps(job), encoding="utf-8")
    running_path.unlink()
    return root, pending, job


class RuntimeJobRunnerTests(unittest.TestCase):
    def test_worker_has_isolated_degradation_dispatch(self):
        source=(ROOT/"analytics/runtime_worker.py").read_text()
        self.assertIn('"degradation_evidence"',source)
        self.assertIn('"degradation-staging"',source)
        self.assertIn('"degradation-evidence"',source)
        self.assertIn('"degradation/latest.json"',source)
        self.assertIn('"degradation/latest_p2-v2.json"',source)
    def test_worker_has_isolated_model_lifecycle_dispatch(self):
        source=(ROOT/"analytics/runtime_worker.py").read_text()
        self.assertIn('"model_lifecycle"',source)
        self.assertIn('"lifecycle-staging"',source)
        self.assertIn('"model-lifecycle"',source)
        self.assertIn('"model-assignment/latest.json"',source)
    def test_atomic_claim_has_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            ensure_structure(root)
            job_id = str(uuid.uuid4())
            (root / "jobs/pending" / f"{job_id}.json").write_text(json.dumps({"jobId": job_id}))
            claimed = claim_one(root)
            self.assertEqual(claimed, root / "jobs/running" / f"{job_id}.json")
            self.assertIsNone(claim_one(root))
            self.assertFalse((root / "jobs/pending" / f"{job_id}.json").exists())

    def test_worker_claims_executes_and_completes_committed_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root, pending, job = build_pending_governed_quick_job(Path(directory))
            self.assertTrue(run_once(root, "test-worker"))
            completed = root / "jobs/completed" / pending.name
            failed = root / "jobs/failed" / pending.name
            diagnostics = failed.read_text() if failed.exists() else "missing job record"
            stderr_candidates = list((root / "staging").glob("*/logs/stderr.log")) + list((root / "runs").glob("*/logs/stderr.log"))
            if stderr_candidates:
                diagnostics += "\n" + stderr_candidates[0].read_text(errors="replace")
            self.assertTrue(completed.exists(), diagnostics)
            value = json.loads(completed.read_text())
            self.assertEqual(value["status"], "completed")
            self.assertEqual(value["committedRunId"], job["runId"])

    def test_worker_executes_archived_quick_2_0_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root, pending, job = build_pending_governed_quick_job(
                Path(directory), schema_version="2.0"
            )
            self.assertTrue(run_once(root, "archived-quick-worker"))
            completed = root / "jobs/completed" / pending.name
            failed = root / "jobs/failed" / pending.name
            self.assertTrue(
                completed.exists(),
                failed.read_text() if failed.exists() else "missing job record",
            )
            value = json.loads(completed.read_text())
            self.assertEqual(value["status"], "completed")
            self.assertEqual(value["committedRunId"], job["runId"])
            run_root = root / "runs" / job["runId"]
            for relative in (
                "metadata/run.json",
                "artifacts/forecast_output.json",
                "artifacts/model_card.json",
            ):
                artifact = json.loads((run_root / relative).read_text())
                self.assertEqual(artifact["schemaVersion"], "2.0")
                self.assertNotIn("assignmentAction", artifact)
                self.assertNotIn("authoritySnapshotSha256", artifact)
            commit = json.loads((run_root / "metadata/commit.json").read_text())
            self.assertEqual(commit["schemaVersion"], "1.0")
            self.assertNotIn("runRecordSha256", commit)

    def test_worker_load_rejects_unknown_or_malformed_quick_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            root, pending, job = build_pending_governed_quick_job(Path(directory))
            load_job(pending)
            invalid_jobs = {
                "unknown schema": {**job, "schemaVersion": "9.9"},
                "unknown kind": {**job, "jobKind": "unknown_job"},
                "wrong policy": {**job, "policyVersion": "p9-v1"},
                "missing authority": {
                    key: value for key, value in job.items() if key != "assignmentId"
                },
                "extra property": {**job, "unsupportedField": True},
            }
            invalid_path = root / "jobs/pending/invalid.json"
            for label, invalid in invalid_jobs.items():
                with self.subTest(label=label):
                    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
                    with self.assertRaises(ValidationError):
                        load_job(invalid_path)

    def test_worker_executes_outcome_without_validation_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root, workspace, forecast_path, forecast_job = build_ready_runtime(Path(directory))
            execute_historical_quick_forecast(root, workspace, forecast_path, forecast_job)
            outcome_job, running = build_outcome_job(
                root,
                forecast_job,
                record_id="worker-observation",
                schema_version="2.1",
            )
            outcome_job.update(status="queued", progress="queued", claimedAt=None, startedAt=None, heartbeatAt=None, workerId=None)
            pending=root/"jobs/pending"/running.name;pending.write_text(json.dumps(outcome_job));running.unlink()
            self.assertTrue(run_once(root,"outcome-worker"))
            completed=root/"jobs/completed"/pending.name
            self.assertTrue(completed.exists(),(root/"jobs/failed"/pending.name).read_text() if (root/"jobs/failed"/pending.name).exists() else "missing")
            value=json.loads(completed.read_text());self.assertEqual(value["committedOutcomeId"],outcome_job["outcomeId"])
            self.assertTrue((root/"deployments/dhaka_south/monitoring/latest.json").exists())

    def test_worker_executes_p2_v2_degradation_and_requires_versioned_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root, _, forecast_job = build_pending_governed_quick_job(Path(directory), "2.1")
            self.assertTrue(run_once(root, "degradation-source-worker"))
            outcome_job, running = build_outcome_job(
                root,
                forecast_job,
                record_id="worker-degradation-p2-v2",
                schema_version="2.1",
            )
            execute_outcome(
                SimpleNamespace(
                    runtime_root=str(root),
                    job_record=str(running),
                    staging=str(root / "outcome-staging" / outcome_job["outcomeId"]),
                )
            )
            job, running = degradation_job(root)
            job.update(
                status="queued",
                progress="queued",
                claimedAt=None,
                startedAt=None,
                heartbeatAt=None,
                workerId=None,
            )
            pending = root / "jobs/pending" / running.name
            pending.write_text(json.dumps(job), encoding="utf-8")
            running.unlink()
            self.assertTrue(run_once(root, "degradation-p2-v2-worker"))
            completed = root / "jobs/completed" / pending.name
            failed = root / "jobs/failed" / pending.name
            self.assertTrue(
                completed.is_file(),
                failed.read_text() if failed.is_file() else "missing degradation job record",
            )
            value = json.loads(completed.read_text())
            self.assertEqual(value["committedEvidenceId"], job["evidenceId"])
            self.assertTrue(
                (root / "deployments/dhaka_south/degradation/latest_p2-v2.json").is_file()
            )
            self.assertFalse(
                (root / "deployments/dhaka_south/degradation/latest.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
