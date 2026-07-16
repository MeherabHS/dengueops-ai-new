import copy
import math
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from empirical_range import (
    FEATURE_COLUMNS, advance_iso_period, build_prequential_evaluation,
    build_runtime_fold_plan, construct_raw_interval, finite_sample_quantile,
    generate_runtime_rf_residuals,
)
from feature_engineering import build_features
from model_factory import load_and_validate_candidate_registry


class RuntimeEmpiricalCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame, _ = build_features(ROOT / "data/dengue_cases.csv", ROOT / "data/climate_data.csv", output_path=None)
        cls.registry, cls.registry_sha = load_and_validate_candidate_registry()
        cls.candidate = next(value for value in cls.registry["candidates"] if value["model_id"] == "random_forest")
        cls.result = generate_runtime_rf_residuals(
            cls.frame, cls.registry, registry_sha256=cls.registry_sha,
            expected_registry_sha256=cls.registry_sha,
            expected_parameters_sha256=cls.candidate["parameters_sha256"],
        )

    def generate(self, frame=None):
        return generate_runtime_rf_residuals(
            self.frame if frame is None else frame, self.registry,
            registry_sha256=self.registry_sha, expected_registry_sha256=self.registry_sha,
            expected_parameters_sha256=self.candidate["parameters_sha256"],
        )

    def test_exact_fold_count_boundaries_alignment_and_out_of_sample_design(self):
        plan, _ = build_runtime_fold_plan(self.frame)
        self.assertEqual(len(plan), 68)
        self.assertEqual((plan[0]["trainingRowCount"], plan[0]["embargoIndex"], plan[0]["validationIndex"]), (104, 104, 105))
        self.assertEqual((plan[-1]["trainingRowCount"], plan[-1]["embargoIndex"], plan[-1]["validationIndex"]), (171, 171, 172))
        for fold in plan:
            self.assertEqual(fold["trainEndExclusive"], fold["embargoIndex"])
            self.assertEqual(fold["validationIndex"], fold["embargoIndex"] + 1)
            validation = self.frame.iloc[fold["validationIndex"]]
            year, week = advance_iso_period(int(validation.epi_year), int(validation.epi_week), 2)
            self.assertEqual(fold["targetPeriod"], f"{year}-W{week:02d}")
            latest_train = self.frame.iloc[fold["trainEndExclusive"] - 1]
            label_year, label_week = advance_iso_period(int(latest_train.epi_year), int(latest_train.epi_week), 2)
            self.assertLessEqual((label_year, label_week), (int(validation.epi_year), int(validation.epi_week)))

    def test_deterministic_repeated_execution_and_exact_residual_count(self):
        repeated = self.generate()
        self.assertEqual(self.result["status"], "available")
        self.assertEqual(len(self.result["folds"]), 68)
        self.assertEqual(
            [(row["rawPrediction"], row["signedResidual"], row["absoluteResidual"]) for row in self.result["folds"]],
            [(row["rawPrediction"], row["signedResidual"], row["absoluteResidual"]) for row in repeated["folds"]],
        )

    def test_quantile_coverage_misses_widths_and_containment(self):
        records, metrics = build_prequential_evaluation(self.result["residuals"])
        rank, quantile = finite_sample_quantile([row["absolute_residual"] for row in self.result["residuals"]])
        self.assertEqual((rank, len(records), metrics["residual_count"]), (63, 48, 68))
        self.assertAlmostEqual(quantile, 66.48030596275706)
        self.assertEqual(metrics["covered_fold_count"] + metrics["lower_miss_count"] + metrics["upper_miss_count"], 48)
        self.assertAlmostEqual(metrics["observed_coverage"], metrics["covered_fold_count"] / 48)
        widths = [row["upper_raw"] - row["lower_raw"] for row in records]
        self.assertAlmostEqual(metrics["minimum_interval_width"], min(widths))
        self.assertAlmostEqual(metrics["maximum_interval_width"], max(widths))
        bounds = construct_raw_interval(12.25, quantile)
        self.assertEqual(bounds["lower_raw"], 0.0)
        self.assertTrue(math.isfinite(bounds["upper_raw"]))
        self.assertLessEqual(bounds["lower_raw"], 12.25)
        self.assertLessEqual(12.25, bounds["upper_raw"])
        self.assertLessEqual(math.floor(bounds["lower_raw"]), round(12.25))
        self.assertLessEqual(round(12.25), math.ceil(bounds["upper_raw"]))

    def test_feature_period_value_and_identity_failures_are_closed(self):
        reordered = self.frame[[*self.frame.columns[:9], FEATURE_COLUMNS[1], FEATURE_COLUMNS[0], *self.frame.columns[11:]]]
        with self.assertRaisesRegex(ValueError, "feature order"):
            self.generate(reordered)
        duplicate = self.frame.copy()
        duplicate.loc[1, ["epi_year", "epi_week"]] = duplicate.loc[0, ["epi_year", "epi_week"]].to_numpy()
        with self.assertRaisesRegex(ValueError, "duplicates"):
            self.generate(duplicate)
        unordered = pd.concat([self.frame.iloc[[1]], self.frame.iloc[[0]], self.frame.iloc[2:]], ignore_index=True)
        with self.assertRaisesRegex(ValueError, "not chronological"):
            self.generate(unordered)
        nonfinite = self.frame.copy()
        nonfinite.loc[0, FEATURE_COLUMNS[0]] = np.inf
        with self.assertRaisesRegex(ValueError, "non-finite"):
            self.generate(nonfinite)
        with self.assertRaisesRegex(ValueError, "registry identity"):
            generate_runtime_rf_residuals(self.frame, self.registry, registry_sha256="0" * 64,
                expected_registry_sha256=self.registry_sha, expected_parameters_sha256=self.candidate["parameters_sha256"])

    def test_nonfinite_prediction_or_residual_fails_closed(self):
        class InvalidEstimator:
            def fit(self, *_): return self
            def predict(self, *_): return np.asarray([np.inf])
        with patch("empirical_range.build_candidate_estimator", return_value=InvalidEstimator()):
            with self.assertRaisesRegex(ValueError, "non-finite"):
                self.generate()
        invalid_target = self.frame.copy()
        invalid_target.loc[105, "target_cases_next_2w"] = np.nan
        with self.assertRaisesRegex(ValueError, "non-finite"):
            self.generate(invalid_target)

    def test_non_exact_fold_counts_remain_pending_without_partial_residuals(self):
        short = self.generate(self.frame.iloc[:-1].copy())
        self.assertEqual(short["status"], "pending_dataset_specific_calibration")
        self.assertEqual((short["folds"], short["residuals"]), ([], []))
        extra = self.frame.iloc[-1].copy()
        monday = date.fromisocalendar(int(extra.epi_year), int(extra.epi_week), 1) + timedelta(weeks=1)
        year, week, _ = monday.isocalendar()
        extra["epi_year"], extra["epi_week"], extra["date_start"] = year, week, monday.isoformat()
        long_frame = pd.concat([self.frame, extra.to_frame().T], ignore_index=True)
        long_frame[self.frame.columns] = long_frame[self.frame.columns].astype(self.frame.dtypes.to_dict())
        long = self.generate(long_frame)
        self.assertEqual(long["status"], "pending_dataset_specific_calibration")
        self.assertEqual((long["folds"], long["residuals"]), ([], []))

    def test_iso_week_boundaries_are_date_based_and_week_53_fails_closed(self):
        self.assertEqual(advance_iso_period(2023, 52, 2), (2024, 2))
        with self.assertRaisesRegex(ValueError, "week 53"):
            advance_iso_period(2020, 51, 2)


if __name__ == "__main__":
    unittest.main()
