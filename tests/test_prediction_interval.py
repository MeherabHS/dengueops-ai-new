import copy
import math
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from prediction_interval import (
    PredictionIntervalError,
    build_assessment_calibration,
    calibration_metrics,
    construct_count_interval,
    finite_sample_quantile,
    load_and_validate_uncertainty_policy,
    verify_assessment_calibration,
)


def scientific(status="passed"):
    return {
        "validationStrategy": "rolling_origin_expanding_window", "foldCountRequired": 10,
        "foldCountCompleted": 10, "targetHorizonWeeks": 2, "purgeGapWeeks": 2,
        "featureAvailabilityPolicy": {"policyId": "RUNTIME.MODEL_ASSESSMENT.TEMPORAL_VALIDATION", "policyVersion": "b9.l-v1", "policySha256": "a" * 64},
        "preprocessingScope": "fold_training_rows_only", "datasetSnapshotClassification": "retrospective_latest_revision",
        "trueHistoricalVintageDataAvailable": False, "qualificationScope": "workflow_execution_on_assessment_history",
        "qualificationUntouchedHoldout": False, "leakageAuditStatus": status,
    }


def folds():
    result = []
    for index in range(10):
        actual = float(20 + index)
        result.append({
            "foldId": f"fold-{index}", "forecastOrigin": f"2024-W{index + 1:02d}", "targetPeriod": f"2024-W{index + 3:02d}",
            "actualTarget": actual,
            "predictions": [
                {"modelId": "candidate_a", "foldStatus": "success", "rawPrediction": actual - index, "absoluteError": float(index)},
                {"modelId": "candidate_b", "foldStatus": "success", "rawPrediction": actual - 50, "absoluteError": 50.0},
            ],
        })
    return result


class PredictionIntervalTests(unittest.TestCase):
    def test_governed_policy_and_finite_sample_order_statistic(self):
        policy, digest = load_and_validate_uncertainty_policy()
        self.assertEqual(policy["policy_sha256"], digest)
        self.assertEqual(policy["minimum_calibration_observations"], 9)
        self.assertEqual(finite_sample_quantile([4, 1, 3, 2, 2, 8, 5, 6, 7], 0.9), (9, 8.0))
        self.assertEqual(finite_sample_quantile([0, 0, 0, 0, 0, 0, 0, 0, 0], 0.9), (9, 0.0))
        with self.assertRaises(PredictionIntervalError): finite_sample_quantile([], 0.9)
        with self.assertRaises(PredictionIntervalError): finite_sample_quantile([1, -1], 0.9)

    def test_count_bounds_are_deterministic_nonnegative_and_contain_point(self):
        self.assertEqual(construct_count_interval(0, 3)["lowerReported"], 0)
        self.assertEqual(construct_count_interval(2, 5)["lowerReported"], 0)
        self.assertEqual(construct_count_interval(2, 5)["upperReported"], 7)
        repeated = [construct_count_interval(10.5, 2.25) for _ in range(3)]
        self.assertEqual(repeated[0], repeated[1])
        self.assertLessEqual(repeated[0]["lowerReported"], round(10.5))
        self.assertGreaterEqual(repeated[0]["upperReported"], round(10.5))

    def test_calibration_is_oof_candidate_specific_and_not_pooled(self):
        policy, digest = load_and_validate_uncertainty_policy()
        evidence = build_assessment_calibration(folds(), ["candidate_a", "candidate_b"], scientific(), policy, digest)
        a, b = evidence["candidateCalibrations"]
        self.assertEqual(a["sampleCount"], 10)
        self.assertEqual(a["absoluteResidualQuantile"], 9.0)
        self.assertEqual(b["absoluteResidualQuantile"], 50.0)
        self.assertNotEqual(a["absoluteResidualQuantile"], b["absoluteResidualQuantile"])
        # Near-zero in-sample errors are not accepted by this API; only fold OOF records exist.
        self.assertNotIn("trainingResiduals", evidence)

    def test_insufficient_failed_and_tampered_evidence_fail_closed(self):
        policy, digest = load_and_validate_uncertainty_policy()
        short = folds()[:8]
        short_scientific = scientific(); short_scientific.update(foldCountRequired=8, foldCountCompleted=8)
        evidence = build_assessment_calibration(short, ["candidate_a"], short_scientific, policy, digest)
        self.assertEqual(evidence["candidateCalibrations"][0]["status"], "point_only")
        failed = folds(); failed[0]["predictions"][0]["foldStatus"] = "failed"
        failed_evidence = build_assessment_calibration(failed, ["candidate_a"], scientific(), policy, digest)
        self.assertEqual(failed_evidence["candidateCalibrations"][0]["status"], "point_only")
        with self.assertRaises(PredictionIntervalError):
            build_assessment_calibration(folds(), ["candidate_a"], scientific("failed"), policy, digest)
        tampered = folds(); tampered[0]["predictions"][0]["absoluteError"] = 999
        with self.assertRaises(PredictionIntervalError):
            build_assessment_calibration(tampered, ["candidate_a"], scientific(), policy, digest)

    def test_committed_summary_and_synthetic_coverage_recompute(self):
        policy, digest = load_and_validate_uncertainty_policy()
        source_folds = folds()
        calibration = build_assessment_calibration(source_folds, ["candidate_a", "candidate_b"], scientific(), policy, digest)
        rolling = {"deploymentId": "dhaka_south", "candidateIds": ["candidate_a", "candidate_b"], "folds": source_folds,
            "scientificValidation": scientific(), "uncertaintyCalibration": calibration}
        self.assertEqual(verify_assessment_calibration(rolling), calibration)
        altered = copy.deepcopy(rolling); altered["uncertaintyCalibration"]["candidateCalibrations"][0]["absoluteResidualQuantile"] += 1
        with self.assertRaises(PredictionIntervalError): verify_assessment_calibration(altered)
        residuals = [{"actualTarget": row["actualTarget"], "rawPrediction": row["predictions"][0]["rawPrediction"]} for row in source_folds]
        metrics = calibration_metrics(residuals, 9.0)
        self.assertTrue(math.isfinite(metrics["historicalCoverage"]))
        self.assertGreaterEqual(metrics["historicalCoverage"], 0.8)


if __name__ == "__main__":
    unittest.main()
