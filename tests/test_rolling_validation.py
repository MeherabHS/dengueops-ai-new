from __future__ import annotations
import math, sys, unittest
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
from feature_engineering import FEATURE_COLUMNS
from validation_backtest import GBR_PARAMS, build_rolling_validation

class RollingValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact = build_rolling_validation(pd.read_csv(ROOT / "data" / "model_features.csv"))

    def test_fold_boundaries_and_embargo(self):
        folds = self.artifact["folds"]
        self.assertEqual(len(folds), 68)
        self.assertEqual((folds[0]["train_start"], folds[0]["train_end"], folds[0]["train_rows"], folds[0]["embargo_period"], folds[0]["origin_period"], folds[0]["target_period"]),
                         ("2021-W06", "2023-W05", 104, "2023-W06", "2023-W07", "2023-W09"))
        self.assertEqual((folds[-1]["train_end"], folds[-1]["train_rows"], folds[-1]["embargo_period"], folds[-1]["origin_period"], folds[-1]["target_period"]),
                         ("2024-W20", 171, "2024-W21", "2024-W22", "2024-W24"))
        for fold in folds:
            self.assertLessEqual(fold["latest_training_target_period"], fold["origin_period"])
            self.assertEqual(len({fold["train_end"], fold["embargo_period"], fold["origin_period"]}), 3)

    def test_models_metrics_and_importance(self):
        self.assertEqual(len(FEATURE_COLUMNS), 18)
        self.assertEqual(GBR_PARAMS, {"n_estimators": 200, "learning_rate": .05, "max_depth": 4, "min_samples_leaf": 3, "subsample": .8, "random_state": 42, "loss": "squared_error"})
        for fold in self.artifact["folds"]:
            self.assertEqual(set(fold["predictions"]), {"gradient_boosting", "naive", "moving_average"})
            for record in fold["predictions"].values():
                self.assertTrue(math.isfinite(record["prediction"])); self.assertGreaterEqual(record["prediction"], 0)
        self.assertEqual(self.artifact["native_importance_stability"]["folds_evaluated"], 68)
        self.assertEqual(len(self.artifact["native_importance_stability"]["features"]), 18)
        self.assertEqual(self.artifact["permutation_stability_status"], "not_evaluated_single_row_folds")
        self.assertNotIn("seasonal_naive", str(self.artifact))

    def test_population_std_quartiles_and_result_driven_winner(self):
        metric = self.artifact["aggregate_metrics"]["gradient_boosting"]
        errors = [f["predictions"]["gradient_boosting"]["absolute_error"] for f in self.artifact["folds"]]
        import numpy as np
        self.assertAlmostEqual(metric["absolute_error_standard_deviation"], float(np.std(errors, ddof=0)))
        self.assertEqual(sum(self.artifact["variability_summary"]["target_volume_quartile_bin_counts"]), 68)
        winner = min(self.artifact["model_comparison"], key=lambda row: row["mae"])["model_name"]
        self.assertIn(winner, {"gradient_boosting", "naive", "moving_average"})

if __name__ == "__main__": unittest.main()
