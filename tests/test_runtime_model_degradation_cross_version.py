import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_forecast_outcome import execute as execute_outcome
from runtime_model_degradation_commit import _verify_committed
from runtime_model_degradation_evidence import execute as execute_degradation
from runtime_model_degradation_source import verify_model_degradation_snapshot
from runtime_quick_forecast import execute as execute_quick_forecast
from runtime_worker import run_once
from tests.test_runtime_forecast_outcome import build_outcome_job
from tests.test_runtime_job_runner import build_pending_governed_quick_job
from tests.test_runtime_model_degradation_evidence import degradation_job
from tests.test_product_v2_quick_forecast import _setup_quick_run_job, build_ready_workspace


def _publish_outcome(runtime: Path, forecast_job: dict, record_id: str) -> None:
    job, path = build_outcome_job(
        runtime,
        forecast_job,
        record_id=record_id,
        schema_version="2.1",
    )
    execute_outcome(
        SimpleNamespace(
            runtime_root=str(runtime),
            job_record=str(path),
            staging=str(runtime / "outcome-staging" / job["outcomeId"]),
        )
    )


def _publish_degradation(runtime: Path) -> tuple[dict, Path]:
    job, path = degradation_job(runtime)
    result = execute_degradation(
        SimpleNamespace(
            runtime_root=str(runtime),
            job_record=str(path),
            staging=str(runtime / "degradation-staging" / job["evidenceId"]),
        )
    )
    return result, runtime / "degradation-evidence" / result["commit"]["evidenceId"]


def _publish_another_forecast(runtime: Path) -> dict:
    workspace, dataset_id, validation_sha = build_ready_workspace(runtime)
    job, running, staging = _setup_quick_run_job(
        runtime,
        workspace.name,
        dataset_id,
        validation_sha,
    )
    result = execute_quick_forecast(
        SimpleNamespace(
            runtime_root=str(runtime),
            job_record=str(running),
            workspace=str(workspace),
            staging=str(staging),
        )
    )
    if not result["committed"]:
        raise AssertionError("second quick p2 forecast did not execute")
    return job


def build_cross_version_runtime(base: Path) -> dict:
    runtime, _, forecast_job = build_pending_governed_quick_job(base, "2.1")
    if not run_once(runtime, "b8-cross-version"):
        raise AssertionError("first quick p2 forecast did not execute")
    historical_pointer = runtime / "deployments/dhaka_south/degradation/latest.json"
    historical_pointer.parent.mkdir(parents=True, exist_ok=True)
    historical_bytes = b'{"historical":"p2-v1-pointer-bytes"}\n'
    historical_pointer.write_bytes(historical_bytes)
    _publish_outcome(runtime, forecast_job, "b8-m1")
    d1, d1_root = _publish_degradation(runtime)
    d1_snapshot = (d1_root / "artifacts/monitoring_latest_snapshot.json").read_bytes()
    second_forecast_job = _publish_another_forecast(runtime)
    _publish_outcome(runtime, second_forecast_job, "b8-m2")
    d2, d2_root = _publish_degradation(runtime)
    return {
        "runtime": runtime,
        "historicalPointer": historical_pointer,
        "historicalBytes": historical_bytes,
        "d1": d1,
        "d1Root": d1_root,
        "d1Snapshot": d1_snapshot,
        "d2": d2,
        "d2Root": d2_root,
    }


class RuntimeModelDegradationCrossVersionTests(unittest.TestCase):
    def test_d1_snapshot_remains_verifiable_after_m2_and_d2(self):
        with tempfile.TemporaryDirectory() as directory:
            built = build_cross_version_runtime(Path(directory))
            runtime=built["runtime"];historical_pointer=built["historicalPointer"];historical_bytes=built["historicalBytes"]
            d1=built["d1"];d1_root=built["d1Root"];d1_snapshot=built["d1Snapshot"];d2=built["d2"];d2_root=built["d2Root"]
            d1_commit_sha = d1["pointer"]["commitSha256"]

            self.assertNotEqual(d1_root, d2_root)
            self.assertNotEqual(d1["commit"]["evidenceId"], d2["commit"]["evidenceId"])
            self.assertEqual(historical_pointer.read_bytes(), historical_bytes)
            current = json.loads(
                (runtime / "deployments/dhaka_south/degradation/latest_p2-v2.json").read_text()
            )
            self.assertEqual(current["evidenceId"], d2["commit"]["evidenceId"])
            self.assertEqual(d1["pointer"]["commitSha256"], d1_commit_sha)

            committed, evidence, summary = _verify_committed(d1_root)
            historical_source = verify_model_degradation_snapshot(
                runtime,
                d1_snapshot,
                committed["monitoringLatestSnapshotSha256"],
                committed["monitoringSummarySha256"],
                committed["includedOutcomeSetSha256"],
                "p2-v2",
            )
            self.assertEqual(historical_source["summarySha256"], committed["monitoringSummarySha256"])
            self.assertEqual(
                historical_source["summary"]["outcomeSetSha256"],
                summary["includedOutcomeSetSha256"],
            )
            self.assertEqual(evidence["evidenceId"], d1["commit"]["evidenceId"])


if __name__ == "__main__":
    unittest.main()
