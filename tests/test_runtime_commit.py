import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))
from runtime_commit import RuntimeCommitError, commit_runtime_run


class RuntimeCommitTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
