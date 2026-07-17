import math
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from forecast_outcome_metrics import aggregate_outcomes, calculate_period_completion, evaluate_outcome, parse_target_period


class ForecastOutcomeMetricTests(unittest.TestCase):
    def test_signed_percentage_and_range_metrics(self):
        value = evaluate_outcome(80.5, 100, {"uncertaintyStatus": "available", "lowerRaw": 70.25, "upperRaw": 110.75})
        self.assertEqual(value["signedError"], 19.5)
        self.assertEqual(value["errorDirection"], "underforecast")
        self.assertEqual(value["absoluteError"], 19.5)
        self.assertEqual(value["squaredError"], 380.25)
        self.assertEqual(value["percentageError"], 19.5)
        self.assertEqual(value["absolutePercentageError"], 19.5)
        self.assertEqual(value["coverageOutcome"], "covered")
        self.assertEqual(value["intervalWidth"], 40.5)

    def test_overforecast_zero_and_pending_metrics(self):
        zero = evaluate_outcome(2.5, 0, {"uncertaintyStatus": "pending_dataset_specific_calibration", "lowerRaw": None, "upperRaw": None}, True)
        self.assertEqual(zero["signedError"], -2.5)
        self.assertEqual(zero["errorDirection"], "overforecast")
        self.assertIsNone(zero["percentageError"])
        self.assertFalse(zero["percentageErrorEligible"])
        self.assertEqual(zero["percentageMetricStatus"], "not_evaluable_zero_observed")
        self.assertEqual(zero["coverageOutcome"], "not_evaluable_no_empirical_range")
        self.assertEqual(evaluate_outcome(10, 5, {"uncertaintyStatus":"available","lowerRaw":6,"upperRaw":12})["coverageOutcome"], "lower_miss")
        self.assertEqual(evaluate_outcome(10, 13, {"uncertaintyStatus":"available","lowerRaw":6,"upperRaw":12})["coverageOutcome"], "upper_miss")
        approved=evaluate_outcome(10,5,{"uncertaintyStatus":"pending_selected_model_calibration","lowerRaw":None,"upperRaw":None},True)
        self.assertTrue(approved["percentageErrorEligible"]);self.assertEqual(approved["coverageOutcome"],"not_evaluable_no_empirical_range")

    def test_aggregation_is_deterministic_and_full_precision(self):
        base = [
            {"outcomeId":"b","forecastRunId":"b","forecastTargetPeriod":"2024-W02",**evaluate_outcome(1.1, 2, {"uncertaintyStatus":"available","lowerRaw":1,"upperRaw":2})},
            {"outcomeId":"a","forecastRunId":"a","forecastTargetPeriod":"2024-W01",**evaluate_outcome(2.2, 0, {"uncertaintyStatus":"pending_dataset_specific_calibration","lowerRaw":None,"upperRaw":None})},
        ]
        first, second = aggregate_outcomes(base), aggregate_outcomes(list(reversed(base)))
        self.assertEqual(first, second)
        self.assertEqual(first["evaluatedForecastCount"], 2)
        self.assertAlmostEqual(first["cumulativeMAE"], (0.9 + 2.2) / 2)
        self.assertAlmostEqual(first["cumulativeRMSE"], math.sqrt((0.81 + 4.84) / 2))
        self.assertAlmostEqual(first["cumulativeBias"], (0.9 - 2.2) / 2)
        self.assertAlmostEqual(first["cumulativeMPE"], 45.0)
        self.assertAlmostEqual(first["cumulativeMAPE"], 45.0)
        self.assertEqual(first["empiricalCoverage"], 1.0)

    def test_iso_completion_and_validation(self):
        self.assertEqual(parse_target_period("2024-W52"), (2024, 52))
        self.assertEqual(calculate_period_completion("2024-W52"), datetime(2024, 12, 29, 18, tzinfo=timezone.utc))
        for invalid in ("2024-52", "2024-W00", "2020-W53"):
            with self.assertRaises(ValueError): parse_target_period(invalid)

    def test_invalid_numeric_inputs_fail_closed(self):
        for observed in (-1, 1.5, True):
            with self.assertRaises(ValueError): evaluate_outcome(1, observed, {"uncertaintyStatus":"pending_dataset_specific_calibration","lowerRaw":None,"upperRaw":None})
        with self.assertRaises(ValueError): evaluate_outcome(float("nan"), 1, {"uncertaintyStatus":"pending_dataset_specific_calibration","lowerRaw":None,"upperRaw":None})


if __name__ == "__main__": unittest.main()
