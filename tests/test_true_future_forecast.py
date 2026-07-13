from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from feature_engineering import (  # noqa: E402
    FEATURE_COLUMNS,
    build_features,
    build_inference_features,
)
from forecast_model import HORIZON_DAYS, advance_epi_week, generate_forecast  # noqa: E402


class RecordingModel:
    def __init__(self, prediction: float = 180.0) -> None:
        self.prediction = prediction
        self.last_input: np.ndarray | None = None

    def predict(self, values: np.ndarray) -> np.ndarray:
        self.last_input = values.copy()
        return np.array([self.prediction])


class TrueFutureForecastTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        data_dir = Path(self.temp_dir.name)
        self.dengue_path = data_dir / "dengue_cases.csv"
        self.climate_path = data_dir / "climate_data.csv"

        weeks = list(range(1, 25))
        dates = [date.isoformat() for date in pd.date_range("2025-12-29", periods=24, freq="7D")]

        pd.DataFrame(
            {
                "epi_year": [2026] * 24,
                "epi_week": weeks,
                "date_start": dates,
                "city": ["Dhaka South"] * 24,
                "cases": [50 + week * 7 for week in weeks],
                "deaths": [0] * 24,
                "source_type": ["test_fixture"] * 24,
            }
        ).to_csv(self.dengue_path, index=False)

        pd.DataFrame(
            {
                "epi_year": [2026] * 24,
                "epi_week": weeks,
                "date_start": dates,
                "rainfall_mm": [10.0 + week for week in weeks],
                "avg_temp_c": [27.0 + (week % 3) * 0.2 for week in weeks],
                "humidity_pct": [65.0 + (week % 5) for week in weeks],
                "source_type": ["test_fixture"] * 24,
            }
        ).to_csv(self.climate_path, index=False)

        self.training_df, _ = build_features(
            self.dengue_path,
            self.climate_path,
            output_path=None,
        )
        self.inference_df = build_inference_features(
            self.dengue_path,
            self.climate_path,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_supervised_table_ends_before_inference_table(self) -> None:
        self.assertEqual(int(self.training_df.iloc[-1]["epi_week"]), 22)
        self.assertEqual(int(self.inference_df.iloc[-1]["epi_week"]), 24)
        self.assertLess(
            int(self.training_df.iloc[-1]["epi_week"]),
            int(self.inference_df.iloc[-1]["epi_week"]),
        )

    def test_raw_w24_produces_w24_inference_row(self) -> None:
        latest = self.inference_df.iloc[-1]
        self.assertEqual((int(latest["epi_year"]), int(latest["epi_week"])), (2026, 24))
        self.assertEqual(int(latest["cases"]), 50 + 24 * 7)

    def test_inference_row_is_not_an_unknown_target_training_row(self) -> None:
        self.assertFalse(self.training_df["target_cases_next_2w"].isna().any())
        self.assertNotIn(24, self.training_df["epi_week"].astype(int).tolist())

        latest = self.inference_df.iloc[-1]
        self.assertTrue(math.isnan(float(latest["target_cases_next_2w"])))

    def test_w24_forecast_targets_w26_and_uses_w24_features(self) -> None:
        model = RecordingModel()
        latest = self.inference_df.iloc[-1]
        forecast = generate_forecast(self.training_df, latest, model)

        self.assertEqual(
            (forecast["latest_known_epi_year"], forecast["latest_known_epi_week"]),
            (2026, 24),
        )
        self.assertEqual(
            (forecast["target_epi_year"], forecast["target_epi_week"]),
            (2026, 26),
        )
        self.assertEqual(forecast["horizon_days"], HORIZON_DAYS)
        np.testing.assert_array_equal(
            model.last_input,
            latest[FEATURE_COLUMNS].values.reshape(1, -1),
        )

    def test_year_boundary_rollover_uses_52_week_convention(self) -> None:
        self.assertEqual(advance_epi_week(2026, 50, 2), (2026, 52))
        self.assertEqual(advance_epi_week(2026, 51, 2), (2027, 1))
        self.assertEqual(advance_epi_week(2026, 52, 2), (2027, 2))

    def test_forecast_metadata_separates_training_and_inference(self) -> None:
        forecast = generate_forecast(
            self.training_df,
            self.inference_df.iloc[-1],
            RecordingModel(),
        )
        training_cutoff = (
            forecast["training_cutoff_epi_year"],
            forecast["training_cutoff_epi_week"],
        )
        forecast_origin = (
            forecast["latest_known_epi_year"],
            forecast["latest_known_epi_week"],
        )

        self.assertLessEqual(training_cutoff, forecast_origin)
        self.assertEqual(training_cutoff, (2026, 22))
        self.assertEqual(forecast["latest_observed_cases"], 50 + 24 * 7)

        serialized = json.loads(json.dumps(forecast))
        for field in (
            "latest_known_epi_year",
            "latest_known_epi_week",
            "latest_observed_cases",
            "training_cutoff_epi_year",
            "training_cutoff_epi_week",
            "target_epi_year",
            "target_epi_week",
            "horizon_days",
        ):
            self.assertEqual(serialized[field], forecast[field])

    def test_training_cutoff_after_inference_origin_is_rejected(self) -> None:
        invalid_training = self.training_df.copy()
        invalid_training.loc[invalid_training.index[-1], "epi_year"] = 2027

        with self.assertRaisesRegex(
            ValueError,
            "Training cutoff cannot be later",
        ):
            generate_forecast(
                invalid_training,
                self.inference_df.iloc[-1],
                RecordingModel(),
            )


if __name__ == "__main__":
    unittest.main()
