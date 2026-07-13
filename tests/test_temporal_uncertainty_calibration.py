import copy, hashlib, json, math, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
from uncertainty_engine import (build_prequential_evaluation, finite_sample_quantile,
    validate_uncertainty_artifact)
from run_pipeline import _restore_transaction


class TemporalUncertaintyCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = json.loads((ROOT / "data/forecast_uncertainty.json").read_text())
        cls.comparison = json.loads((ROOT / "data/candidate_model_comparison.json").read_text())

    def test_governed_artifact_and_coverage(self):
        validate_uncertainty_artifact(self.value)
        metrics = self.value["historical_evaluation"]["aggregate_metrics"]
        self.assertEqual((metrics["calibration_warmup_fold_count"], metrics["evaluated_fold_count"]), (20, 48))
        self.assertEqual((metrics["covered_fold_count"], metrics["lower_miss_count"], metrics["upper_miss_count"]), (43, 2, 3))
        self.assertAlmostEqual(metrics["observed_coverage"], 43/48, places=14)
        self.assertAlmostEqual(metrics["average_interval_width"], 146.92429694798778, places=12)
        self.assertFalse(self.value["is_prediction_interval"])
        self.assertTrue(self.value["calibrated_on_synthetic_data"])

    def test_each_fold_uses_exactly_predecessors_and_no_future_leakage(self):
        records = self.value["historical_evaluation"]["records"]
        self.assertEqual([row["prior_residual_count"] for row in records], list(range(20, 68)))
        residuals = [{"fold_id": row["fold_id"], "absolute_residual": row["absolute_error"]}
                     for row in self.comparison["per_fold_predictions"]["random_forest"]]
        # Supply the remaining fields required by the pure evaluator.
        rolling = {row["fold_id"]: row for row in json.loads((ROOT / "data/rolling_validation.json").read_text())["folds"]}
        for row, prediction in zip(residuals, self.comparison["per_fold_predictions"]["random_forest"]):
            fold = rolling[row["fold_id"]]; row.update(actual=prediction["actual"], raw_prediction=prediction["raw_prediction"],
                target_period=fold["target_period"], case_quartile=fold["target_volume_quartile"], trajectory_category=fold["trajectory"])
        original, _ = build_prequential_evaluation(residuals)
        mutated = copy.deepcopy(residuals); mutated[-1]["absolute_residual"] *= 100
        changed, _ = build_prequential_evaluation(mutated)
        self.assertEqual(original[:-1], changed[:-1])

    def test_order_statistic_no_interpolation_and_final_pool(self):
        rank, value = finite_sample_quantile(list(range(1, 21)))
        self.assertEqual((rank, value), (19, 19.0))
        future = self.value["future_forecast_interval"]
        self.assertEqual((future["residual_pool_count"], future["quantile_rank"]), (68, 63))
        self.assertEqual(future["interval_lower_reported"], math.floor(future["lower_raw"]))
        self.assertEqual(future["interval_upper_reported"], math.ceil(future["upper_raw"]))

    def test_exact_source_hashes_and_schema_rejects_additional_property(self):
        self.assertEqual(self.value["comparison_artifact_sha256"], hashlib.sha256((ROOT / "data/candidate_model_comparison.json").read_bytes()).hexdigest())
        self.assertEqual(self.value["rolling_fold_reference_artifact_sha256"], hashlib.sha256((ROOT / "data/rolling_validation.json").read_bytes()).hexdigest())
        mutated = copy.deepcopy(self.value); mutated["unexpected"] = True
        with self.assertRaises(Exception): validate_uncertainty_artifact(mutated)

    def test_transaction_restore_preserves_previous_commit_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model_card.json"; path.write_bytes(b"old-commit")
            snapshot = {path: path.read_bytes()}; path.write_bytes(b"partial-new-commit")
            _restore_transaction(snapshot)
            self.assertEqual(path.read_bytes(), b"old-commit")


if __name__ == "__main__": unittest.main()
