import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))
from runtime_commit import RuntimeCommitError, commit_runtime_run
from runtime_quick_forecast import execute
from tests.test_runtime_quick_forecast import build_ready_runtime


class RuntimeCommitTests(unittest.TestCase):
    def test_assignment_aware_quick_commit_rechecks_authority(self):
        source=(ROOT/"analytics/runtime_commit.py").read_text()
        self.assertIn("authoritySnapshotSha256",source)
        self.assertIn("active_model_authority_changed_before_commit",source)
    def test_incomplete_bundle_never_creates_latest_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run_id = str(uuid.uuid4())
            staging = root / "staging" / run_id
            (staging / "artifacts").mkdir(parents=True)
            job = {"runId": run_id, "jobId": str(uuid.uuid4()), "workspaceId": str(uuid.uuid4()),
                "datasetId": "a" * 64, "deploymentId": "dhaka_south", "policySha256": "b" * 64}
            with self.assertRaises(RuntimeCommitError):
                commit_runtime_run(root, staging, job)
            self.assertFalse((root / "deployments/dhaka_south/latest.json").exists())

    def test_altered_calibration_fold_is_rejected_before_pointer_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, workspace, job_path, job = build_ready_runtime(Path(directory))
            staging = runtime / "staging" / job["runId"]
            with patch("runtime_quick_forecast.commit_runtime_run", return_value={"pointer": {}}):
                execute(SimpleNamespace(runtime_root=str(runtime), job_record=str(job_path), workspace=str(workspace), staging=str(staging)))
            calibration_path = staging / "artifacts/forecast_calibration.json"
            calibration = json.loads(calibration_path.read_text())
            calibration["folds"][0]["absoluteResidual"] += 1
            calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
            claimed = json.loads(job_path.read_text())
            with self.assertRaises(RuntimeCommitError):
                commit_runtime_run(runtime, staging, claimed)
            self.assertFalse((runtime / "deployments/dhaka_south/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
