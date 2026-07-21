from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_assessment import BASELINE_IDS, CANDIDATE_IDS, LEARNED_IDS
from runtime_assessment_evidence import aggregate_candidate, select_technical_winner


def candidate(model_id, mae, rank, *, learned=True, eligible=True):
    return {
        "modelId": model_id,
        "candidateClass": "learned_model" if learned else "comparison_baseline",
        "selectionEligible": eligible,
        "selectionComplexityRank": rank,
        "metrics": {
            "mae": mae, "rmse": mae, "wape": mae,
            "medianAbsoluteError": mae, "maximumAbsoluteError": mae,
        },
    }


class ProductV2AssessmentEvidenceTests(unittest.TestCase):
    def test_exact_candidate_population(self):
        self.assertEqual(len(CANDIDATE_IDS), 10)
        self.assertEqual(len(LEARNED_IDS), 8)
        self.assertEqual(BASELINE_IDS, {"moving_average_4w", "seasonal_naive_52w"})
        self.assertNotIn("previous_week_naive", CANDIDATE_IDS)

    def test_baseline_and_failed_learned_candidate_cannot_win(self):
        values = [
            candidate("moving_average_4w", 0.0, 1, learned=False),
            candidate("ridge_regression", 2.0, 3),
            candidate("elastic_net", 1.0, 7, eligible=False),
        ]
        winner, _, _, eligible = select_technical_winner(values)
        self.assertEqual(winner, "ridge_regression")
        self.assertEqual(eligible, ["ridge_regression"])

    def test_metric_order_and_tie_break_are_deterministic(self):
        values = [candidate("ridge_regression", 1.0, 4), candidate("elastic_net", 1.0, 3)]
        first = select_technical_winner(values)
        second = select_technical_winner(list(reversed(values)))
        self.assertEqual(first[0], "elastic_net")
        self.assertEqual(second[0], "elastic_net")

    def test_aggregate_includes_mse_and_mathematically_valid_r2(self):
        records = [
            {"foldStatus": "success", "absoluteError": 1.0, "squaredError": 1.0, "clippingApplied": False, "warningCodes": [], "runtimeSeconds": 0.1},
            {"foldStatus": "success", "absoluteError": 2.0, "squaredError": 4.0, "clippingApplied": False, "warningCodes": [], "runtimeSeconds": 0.1},
        ]
        metrics = aggregate_candidate(records, [2.0, 5.0])
        self.assertEqual(metrics["mse"], 2.5)
        self.assertAlmostEqual(metrics["r2"], 1 - 5 / 4.5)
        constant = aggregate_candidate(records, [2.0, 2.0])
        self.assertIsNone(constant["r2"])


if __name__ == "__main__":
    unittest.main()
