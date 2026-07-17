import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))
from runtime_worker import claim_one, ensure_structure, run_once
from runtime_quick_forecast import execute as execute_forecast
from tests.test_runtime_forecast_outcome import build_outcome_job
from tests.test_runtime_quick_forecast import build_ready_runtime
from types import SimpleNamespace


class RuntimeJobRunnerTests(unittest.TestCase):
    def test_worker_has_isolated_degradation_dispatch(self):
        source=(ROOT/"analytics/runtime_worker.py").read_text()
        self.assertIn('"degradation_evidence"',source)
        self.assertIn('"degradation-staging"',source)
        self.assertIn('"degradation-evidence"',source)
        self.assertIn('"degradation/latest.json"',source)
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
            root, _workspace, running_path, job = build_ready_runtime(Path(directory))
            job.update(status="queued", progress="queued", claimedAt=None, startedAt=None, heartbeatAt=None, workerId=None)
            pending = root / "jobs/pending" / running_path.name
            pending.write_text(json.dumps(job), encoding="utf-8")
            running_path.unlink()
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

    def test_worker_executes_outcome_without_validation_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root, workspace, forecast_path, forecast_job = build_ready_runtime(Path(directory))
            execute_forecast(SimpleNamespace(runtime_root=str(root), job_record=str(forecast_path), workspace=str(workspace), staging=str(root / "staging" / forecast_job["runId"])))
            outcome_job, running = build_outcome_job(root, forecast_job, record_id="worker-observation")
            outcome_job.update(status="queued", progress="queued", claimedAt=None, startedAt=None, heartbeatAt=None, workerId=None)
            pending=root/"jobs/pending"/running.name;pending.write_text(json.dumps(outcome_job));running.unlink()
            self.assertTrue(run_once(root,"outcome-worker"))
            completed=root/"jobs/completed"/pending.name
            self.assertTrue(completed.exists(),(root/"jobs/failed"/pending.name).read_text() if (root/"jobs/failed"/pending.name).exists() else "missing")
            value=json.loads(completed.read_text());self.assertEqual(value["committedOutcomeId"],outcome_job["outcomeId"])
            self.assertTrue((root/"deployments/dhaka_south/monitoring/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
