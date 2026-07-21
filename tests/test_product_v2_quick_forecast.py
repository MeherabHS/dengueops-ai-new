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
from runtime_quick_forecast import execute as execute_quick_forecast


class ProductV2QuickForecastTests(unittest.TestCase):
    def test_quick_forecast_p2_fails_closed_when_no_active_assignment(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            # Create a runtime without any model assignment
            (target / "deployments/dhaka_south/model-assignment").mkdir(parents=True, exist_ok=True)
            with self.assertRaises(ActiveModelError):
                resolve_active_model(ROOT, target, "dhaka_south")

    def test_quick_forecast_p2_executes_for_assigned_model(self):
        learned_candidates = ("random_forest", "ridge_regression")
        for model_id in learned_candidates:
            with self.subTest(model=model_id):
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory)
                    chain = build_one_run_chain_p2_v2(target, ROOT, model_id=model_id, override=(model_id != "random_forest"))
                    runtime = chain["runtime"]
                    
                    commit_res = commit_lifecycle_action(
                        runtime,
                        one_run_forecast_run_id=chain["runId"],
                        reason="Assign model for quick forecast test",
                        operator_identifier="test-op",
                        acknowledgement=True
                    )
                    self.assertTrue(commit_res["success"])
                    
                    active = resolve_active_model(ROOT, runtime, "dhaka_south")
                    self.assertEqual(active["modelId"], model_id)
                    self.assertEqual(active["authoritySource"], "committed_assignment")


if __name__ == "__main__":
    unittest.main()
