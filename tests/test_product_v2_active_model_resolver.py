import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "analytics"))

from tests.lifecycle_fixtures import build_one_run_chain_p2_v2
from runtime_model_lifecycle_commit import commit_lifecycle_action
from runtime_active_model import resolve_active_model, ActiveModelError


class ProductV2ActiveModelResolverTests(unittest.TestCase):
    def test_p2_no_assignment_raises_active_model_not_assigned(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with self.assertRaises(ActiveModelError):
                resolve_active_model(ROOT, target, "dhaka_south")

    def test_p2_valid_assignment_resolves_assigned_model(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain = build_one_run_chain_p2_v2(target, ROOT, model_id="poisson_regression", override=True)
            runtime = chain["runtime"]
            commit_res = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="Assign poisson_regression",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertTrue(commit_res["success"], f"Commit failed: {commit_res.get('error')}")


            authority = resolve_active_model(ROOT, runtime, "dhaka_south")
            self.assertEqual(authority["authoritySource"], "committed_assignment")
            self.assertEqual(authority["modelId"], "poisson_regression")
            self.assertEqual(authority["assignmentId"], commit_res["assignmentId"])

    def test_p2_pointer_path_traversal_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain = build_one_run_chain_p2_v2(target, ROOT, model_id="random_forest")
            runtime = chain["runtime"]
            commit_res = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="Valid assign",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertTrue(commit_res["success"], f"Commit failed: {commit_res.get('error')}")


            pointer_path = runtime / "deployments/dhaka_south/model-assignment/latest.json"
            pointer = json.loads(pointer_path.read_text())
            pointer["assignmentId"] = "../../../etc/passwd"
            pointer_path.write_text(json.dumps(pointer))

            with self.assertRaises(ActiveModelError):
                resolve_active_model(ROOT, runtime, "dhaka_south")


if __name__ == "__main__":
    unittest.main()
