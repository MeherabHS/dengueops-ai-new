from __future__ import annotations

import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

import runtime_worker


def job(kind: str) -> dict[str, object]:
    value: dict[str, object] = {
        "jobKind": kind, "jobId": str(uuid.uuid4()), "deploymentId": "dhaka_south",
        "status": "running", "schemaVersion": "2.1", "updatedAt": "2026-08-02T00:00:00Z",
    }
    field = {
        "quick_forecast": "runId", "approved_forecast": "runId", "forecast_outcome": "outcomeId",
        "degradation_evidence": "evidenceId", "model_lifecycle": "lifecycleDecisionId",
        "operational_preparedness": "preparednessId",
    }[kind]
    value[field] = str(uuid.uuid4())
    if kind in {"quick_forecast", "approved_forecast"}:
        value["workspaceId"] = str(uuid.uuid4())
    return value


class RuntimeFinalizationStabilityTests(unittest.TestCase):
    def test_global_lock_is_released_before_every_child_workflow(self):
        for kind in (
            "quick_forecast", "approved_forecast", "forecast_outcome", "degradation_evidence",
            "model_lifecycle", "operational_preparedness",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); runtime_worker.ensure_structure(root)
                claimed = root / "jobs/running/job.json"
                with patch.object(runtime_worker, "claim_one", return_value=claimed), \
                        patch.object(runtime_worker, "execute_claimed", side_effect=lambda *_: self.assertFalse((root / "locks/analytics.lock").exists())):
                    self.assertTrue(runtime_worker.run_once(root, "worker"))
                self.assertFalse((root / "locks/analytics.lock").exists())

    def test_global_lock_is_released_when_any_child_workflow_fails(self):
        for kind in (
            "quick_forecast", "approved_forecast", "forecast_outcome", "degradation_evidence",
            "model_lifecycle", "operational_preparedness",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); runtime_worker.ensure_structure(root)
                claimed = root / "jobs/running/job.json"
                with patch.object(runtime_worker, "claim_one", return_value=claimed), \
                        patch.object(runtime_worker, "execute_claimed", side_effect=RuntimeError("child failure")):
                    self.assertTrue(runtime_worker.run_once(root, "worker"))
                self.assertFalse((root / "locks/analytics.lock").exists())

    def test_bounded_downstream_returns_when_action_hangs(self):
        started = time.monotonic()
        self.assertFalse(runtime_worker.run_bounded_downstream(lambda: time.sleep(1), timeout_seconds=0.01))
        self.assertLess(time.monotonic() - started, 0.25)

    def test_committed_authorities_reconcile_without_child_rerun(self):
        for kind in (
            "quick_forecast", "approved_forecast", "forecast_outcome", "degradation_evidence",
            "model_lifecycle", "operational_preparedness",
        ):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve(); runtime_worker.ensure_structure(root)
                value = job(kind)
                if "workspaceId" in value:
                    (root / "workspaces" / str(value["workspaceId"])).mkdir(parents=True)
                committed, _ = runtime_worker._committed_root(root, value)
                committed.mkdir(parents=True)
                path = root / "jobs/running/job.json"; path.write_text("{}", encoding="utf-8")
                with patch.object(runtime_worker, "load_job", return_value=value), \
                        patch.object(runtime_worker, "verify_committed_job_authority") as verify, \
                        patch.object(runtime_worker, "_complete_existing_job") as complete, \
                        patch.object(runtime_worker, "dispatch_downstream") as downstream, \
                        patch.object(runtime_worker.subprocess, "Popen") as popen:
                    runtime_worker.execute_claimed(root, path, "worker")
                verify.assert_called_once_with(root, value)
                complete.assert_called_once_with(root, path, value)
                downstream.assert_called_once_with(root, value)
                popen.assert_not_called()

    def test_completion_precedes_all_optional_forecast_handoffs(self):
        value = job("quick_forecast")
        calls: list[str] = []
        with patch.object(runtime_worker, "finalize_job", side_effect=lambda *_a, **_k: calls.append("completed")), \
                patch.object(runtime_worker, "dispatch_downstream", side_effect=lambda *_a: calls.append("downstream")):
            runtime_worker._complete_existing_job(Path("C:/runtime"), Path("C:/runtime/jobs/running/job.json"), value)
            runtime_worker.dispatch_downstream(Path("C:/runtime"), value)
        self.assertEqual(calls, ["completed", "downstream"])

    def test_downstream_failures_are_isolated_for_forecast_and_outcome(self):
        for kind in ("quick_forecast", "approved_forecast", "forecast_outcome"):
            with self.subTest(kind=kind), \
                    patch("runtime_governed_monitoring.publish_current_monitoring", side_effect=RuntimeError("monitoring")), \
                    patch("runtime_operational_preparedness.enqueue_operational_preparedness_job", side_effect=RuntimeError("preparedness")):
                statuses = runtime_worker.dispatch_downstream(Path("C:/runtime"), job(kind))
                self.assertTrue(all(value == "failed_or_timed_out" for value in statuses.values()))

    def test_child_producers_do_not_run_optional_downstream_handoffs(self):
        quick = (ROOT / "analytics/runtime_quick_forecast.py").read_text(encoding="utf-8")
        outcome = (ROOT / "analytics/runtime_forecast_outcome.py").read_text(encoding="utf-8")
        preparedness = (ROOT / "analytics/runtime_operational_preparedness.py").read_text(encoding="utf-8")
        self.assertNotIn("publish_current_monitoring", quick)
        self.assertNotIn("publish_current_monitoring", outcome)
        self.assertNotIn("publish_current_monitoring", preparedness)
        self.assertNotIn("enqueue_operational_preparedness_job(root", quick)


if __name__ == "__main__":
    unittest.main()
