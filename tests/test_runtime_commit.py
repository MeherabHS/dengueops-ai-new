import json
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))
from runtime_commit import (
    RuntimeCommitError, commit_runtime_run, sha256_file,
    verify_run_record_binding,
)
from runtime_quick_forecast import execute
from runtime_policy import load_and_validate_quick_forecast_policy
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

    def test_run_record_binding_uses_exact_raw_bytes_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory)
            run_path = run_root / "metadata/run.json"
            run_path.parent.mkdir(parents=True)
            run_path.write_bytes(b'{"schemaVersion":"2.1"}\n')
            commit = {"schemaVersion": "2.1", "runRecordSha256": sha256_file(run_path)}
            verify_run_record_binding(run_root, commit)

            run_path.write_bytes(b'{ "schemaVersion": "2.1" }\n')
            with self.assertRaisesRegex(RuntimeCommitError, "run-record hash mismatch"):
                verify_run_record_binding(run_root, commit)
            with self.assertRaisesRegex(RuntimeCommitError, "run-record hash mismatch"):
                verify_run_record_binding(run_root, {"schemaVersion": "2.1"})
            with self.assertRaisesRegex(RuntimeCommitError, "Historical runtime commits"):
                verify_run_record_binding(run_root, {
                    "schemaVersion": "1.0", "runRecordSha256": "0" * 64,
                })

    def test_commit_schema_requires_only_p21_run_record_binding(self):
        schema = json.loads((ROOT / "config/runtime_commit.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        common = {
            "runId": str(uuid.uuid4()), "jobId": str(uuid.uuid4()),
            "workspaceId": str(uuid.uuid4()), "datasetId": "a" * 64,
            "deploymentId": "dhaka_south", "workflowMode": "quick_forecast",
            "sourceType": "uploaded", "status": "committed", "policySha256": "b" * 64,
            "artifactHashes": {f"artifact-{index}.json": "c" * 64 for index in range(8)},
            "modelCardPublishedLast": True, "prohibitedArtifactsAbsent": True,
            "committedAt": "2026-01-01T00:00:00Z",
        }
        historical = {"schemaVersion": "1.0", **common}
        current = {"schemaVersion": "2.1", **common, "runRecordSha256": "d" * 64}
        self.assertFalse(list(validator.iter_errors(historical)))
        self.assertFalse(list(validator.iter_errors(current)))
        self.assertTrue(list(validator.iter_errors({**historical, "runRecordSha256": "d" * 64})))
        missing = dict(current)
        missing.pop("runRecordSha256")
        self.assertTrue(list(validator.iter_errors(missing)))

    def test_altered_calibration_fold_is_rejected_before_pointer_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, workspace, job_path, job = build_ready_runtime(Path(directory))
            staging = runtime / "staging" / job["runId"]
            policy, policy_hash = load_and_validate_quick_forecast_policy("dhaka_south")
            with patch("runtime_quick_forecast._load_quick_forecast_policy", return_value=(policy, policy_hash, False)), \
                    patch("runtime_quick_forecast.commit_runtime_run", return_value={"pointer": {}}):
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
