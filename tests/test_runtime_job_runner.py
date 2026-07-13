import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))
from runtime_worker import claim_one, ensure_structure, run_once
from tests.test_runtime_quick_forecast import build_ready_runtime


class RuntimeJobRunnerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
