from __future__ import annotations

import math
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from forecast_model import classify_risk, compute_growth_factor  # noqa: E402
from forecast_model import generate_forecast  # noqa: E402
from feature_engineering import build_inference_features  # noqa: E402
from operational_engine import (  # noqa: E402
    EXPOSURE_WEIGHTS, _priority_category, _sdh_alert_level,
    allocate_cases_by_scenario, calculate_bed_load, calculate_priority,
    calculate_sdh, compute_exposure_weights, generate_recommendations,
)
from uncertainty_engine import construct_raw_interval  # noqa: E402


class FormulaBoundaryTest(unittest.TestCase):
    def test_growth_factor_reference_clamps_categories_and_score_continuity(self):
        self.assertEqual(compute_growth_factor(20, 0), 1.0)
        self.assertEqual(compute_growth_factor(0, 100), 0.01)
        self.assertEqual(compute_growth_factor(2000, 1), 10.0)
        self.assertEqual(classify_risk(1.099)[0], "Low")
        self.assertEqual(classify_risk(1.1)[0], "Moderate")
        self.assertEqual(classify_risk(1.5)[0], "High")
        self.assertEqual(classify_risk(2.0)[0], "Critical")
        for boundary in (1.0, 1.1, 1.5, 2.0):
            below = classify_risk(boundary - 1e-6)[1]
            above = classify_risk(boundary + 1e-6)[1]
            self.assertLessEqual(abs(above - below), 1)

    def test_empirical_range_lower_bound_and_point_inclusion(self):
        interval = construct_raw_interval(5, 10)
        self.assertEqual(interval["lower_raw"], 0)
        self.assertTrue(interval["lower_clipping_applied"])
        self.assertLessEqual(interval["lower_raw"], 5)
        self.assertGreaterEqual(interval["upper_raw"], 5)

    def test_negative_model_forecast_is_clipped(self):
        import pandas as pd
        class NegativeModel:
            def predict(self, _values):
                return [-5.0]
        training = pd.read_csv(ROOT / "data" / "model_features.csv")
        inference = build_inference_features().iloc[-1]
        result = generate_forecast(training, inference, NegativeModel())
        self.assertEqual(result["forecast_cases"], 0)

    def test_exposure_weights_precedence_anomaly_normalization_and_conservation(self):
        self.assertAlmostEqual(sum(EXPOSURE_WEIGHTS.values()), 1.0)
        zones = [
            {"zone_id": "A", "exposure_index": 0.2, "population_share": 1, "density_weight": 1, "facility_pressure_weight": 1, "mobility_corridor_weight": 1, "current_anomaly_adjustment": 0.1},
            {"zone_id": "B", "exposure_index": 0.3, "current_anomaly_adjustment": 0.0},
        ]
        enriched = compute_exposure_weights(zones)
        self.assertAlmostEqual(enriched[0]["adjusted_exposure"], 0.3)
        self.assertAlmostEqual(sum(z["normalized_exposure"] for z in enriched), 1.0, places=6)
        allocated = allocate_cases_by_scenario(enriched, 100)
        self.assertAlmostEqual(sum(allocated.values()), 100, places=4)

    def test_admission_fraction_bed_units_and_positive_deficit(self):
        load0, gap0 = calculate_bed_load(5, 10, 14, 14, 4, admission_fraction=0)
        self.assertEqual((load0, gap0), (5.0, 0.0))
        load1, gap1 = calculate_bed_load(5, 7, 14, 14, 4, admission_fraction=1)
        self.assertEqual(load1, 9.0)
        self.assertEqual(gap1, 2.0)
        with self.assertRaises(ValueError):
            calculate_bed_load(0, 1, 1, 14, 4, admission_fraction=1.1)

    def test_facility_allocation_conservation(self):
        directives = json.loads((ROOT / "data" / "directives.json").read_text(encoding="utf-8"))["directives"]
        by_zone = {}
        for row in directives:
            by_zone.setdefault(row["zone_id"], []).append(row)
        for rows in by_zone.values():
            self.assertAlmostEqual(
                sum(row["allocated_cases_expected"] for row in rows),
                rows[0]["zone_allocated_cases_expected"],
                delta=0.11,
            )

    def test_sdh_and_threshold_boundaries(self):
        self.assertTrue(math.isinf(calculate_sdh(10, 0, 1)))
        self.assertEqual(_sdh_alert_level(3, 7), "Critical")
        self.assertEqual(_sdh_alert_level(7, 7), "Warning")
        self.assertEqual(_sdh_alert_level(5, 5), "Warning")
        self.assertEqual(_sdh_alert_level(7.1, 7), "Stable")

    def test_priority_cap_categories_and_directive_boundaries(self):
        self.assertEqual(calculate_priority(100, 1, 1)[0], 100)
        self.assertEqual([_priority_category(v) for v in (25, 26, 50, 51, 75, 76)], ["Routine", "Moderate", "Moderate", "High", "High", "Critical"])
        suggestions = generate_recommendations(7, 7, 5, 5, 0.1, 0.1, 76, "High", "High")
        self.assertTrue(any("Reorder" in value for value in suggestions))
        self.assertTrue(any("beds" in value for value in suggestions))
        self.assertTrue(any("vector-control" in value for value in suggestions))


if __name__ == "__main__":
    unittest.main()
