import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from feature_engineering import build_features
from runtime_assessment import build_common_fold_plan, select_technical_winner
from runtime_assessment_policy import load_and_validate_assessment_policy


class RuntimeCandidateComparisonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, _ = load_and_validate_assessment_policy("dhaka_south")
        cls.frame, _ = build_features(ROOT / "data/dengue_cases.csv", ROOT / "data/climate_data.csv", output_path=None)

    def test_common_plan_has_governed_boundaries_and_stable_identity(self):
        plan, digest = build_common_fold_plan(self.frame, self.policy)
        repeated, repeated_digest = build_common_fold_plan(self.frame.copy(), self.policy)
        self.assertEqual(len(plan), 68)
        self.assertEqual(plan[0]["foldId"], "rolling-origin-0001-2023-W07-to-2023-W09")
        self.assertEqual(plan[-1]["foldId"], "rolling-origin-0068-2024-W22-to-2024-W24")
        self.assertEqual(plan[0]["trainingRowCount"], 104)
        self.assertEqual(plan[-1]["trainingRowCount"], 171)
        self.assertEqual(digest, repeated_digest)
        self.assertEqual(plan, repeated)

    def test_incomplete_candidate_cannot_win_or_change_selector_inputs(self):
        def candidate(model_id, mae, rank, complete=True):
            metrics = {"mae": mae, "rmse": mae + 1, "wape": mae + 2, "medianAbsoluteError": mae, "maximumAbsoluteError": mae + 3}
            return {"modelId": model_id, "selectionEligible": complete, "selectionComplexityRank": rank, "metrics": metrics}
        values = [candidate("previous_week_naive", 20, 1), candidate("random_forest", 10, 6), candidate("gradient_boosting", 1, 7, False)]
        before = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        winner, stage, _steps, eligible = select_technical_winner(values)
        after = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        self.assertEqual(winner, "random_forest")
        self.assertEqual(stage, "mae")
        self.assertNotIn("gradient_boosting", eligible)
        self.assertEqual(before, after)

    def test_mae_first_and_declared_tie_sequence_are_deterministic(self):
        base = {"mae": 5.0, "rmse": 7.0, "wape": 9.0, "medianAbsoluteError": 4.0, "maximumAbsoluteError": 20.0}
        values = [
            {"modelId": "random_forest", "selectionEligible": True, "selectionComplexityRank": 6, "metrics": dict(base)},
            {"modelId": "ridge_regression", "selectionEligible": True, "selectionComplexityRank": 4, "metrics": dict(base)},
        ]
        winner, stage, steps, _eligible = select_technical_winner(values)
        self.assertEqual(winner, "ridge_regression")
        self.assertEqual(stage, "selection_complexity_rank")
        self.assertTrue(steps[0].startswith("mae:"))
        self.assertFalse(any("weighted" in step for step in steps))


if __name__ == "__main__":
    unittest.main()
