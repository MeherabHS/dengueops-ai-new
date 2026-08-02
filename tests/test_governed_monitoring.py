import copy
import hashlib
import json
import math
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from governed_monitoring import (
    GovernedMonitoringError,
    calculate_confidence,
    evaluate_feature_drift,
    evaluate_performance_drift,
    evaluate_ranking_instability,
    load_monitoring_policy,
    population_stability_index,
    reassessment_recommendation,
    reference_quantile_boundaries,
    validate_monitoring_policy,
)
from runtime_governed_monitoring import _verify_existing


class GovernedMonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, cls.policy_sha = load_monitoring_policy()
        cls.features = cls.policy["feature_authority"]["features"]

    def rows(self, values):
        return [{feature: float(value + index / 1000) for index, feature in enumerate(self.features)} for value in values]

    def confidence(self, *, psi=0.01, width=20.0, data_score=1.0, performance=None):
        return calculate_confidence(
            calibration={"status": "governed_available", "sampleCount": 52, "minimumRequired": 9,
                "historicalCoverage": 0.88, "nominalCoverage": 0.9},
            interval={"status": "governed_available", "lowerRaw": 90.0, "upperRaw": 90.0 + width,
                "referenceOutcomeScale": 100.0},
            feature_drift={"status": "stable" if psi < 0.1 else "material_drift", "maximumValue": psi},
            data_quality={"verified": True, "score": data_score},
            performance=performance or {"status": "awaiting_outcomes"}, policy=self.policy,
        )

    def test_identical_distribution_is_near_zero_and_reference_bins_are_reference_only(self):
        values = [float(index % 17) for index in range(104)]
        result = population_stability_index(values, values, maximum_bin_count=10, epsilon=1e-6)
        self.assertAlmostEqual(result["value"], 0.0, places=12)
        before = reference_quantile_boundaries(values, 10)
        after = reference_quantile_boundaries(values, 10)
        population_stability_index(values, [value + 1000 for value in values], maximum_bin_count=10, epsilon=1e-6)
        self.assertEqual(before, after)

    def test_shift_strength_and_single_feature_guard(self):
        reference = self.rows([float(index % 20) for index in range(104)])
        shifted = self.rows([float(index % 20) + 4 for index in range(104)])
        strong = self.rows([float(index % 20) + 100 for index in range(104)])
        mild_result = evaluate_feature_drift(reference, shifted, self.features, self.policy)
        strong_result = evaluate_feature_drift(reference, strong, self.features, self.policy)
        self.assertGreater(strong_result["maximumValue"], mild_result["maximumValue"])
        single = copy.deepcopy(reference)
        for row in single[-52:]: row[self.features[0]] += 100
        one_result = evaluate_feature_drift(reference, single, self.features, self.policy)
        self.assertEqual(one_result["status"], "material_drift")
        self.assertGreaterEqual(one_result["materialFeatureCount"], 1)

    def test_insufficient_and_incompatible_feature_authority(self):
        rows = self.rows(range(20))
        insufficient = evaluate_feature_drift(rows, rows, self.features, self.policy)
        incompatible = evaluate_feature_drift(rows * 3, rows * 3, self.features, self.policy, feature_authority_compatible=False)
        self.assertEqual(insufficient["status"], "insufficient_monitoring_history")
        self.assertEqual(incompatible["status"], "incompatible_feature_authority")

    def test_zero_count_bins_are_finite_and_deterministic(self):
        reference = [float(index) for index in range(100)]
        current = [1000.0] * 100
        first = population_stability_index(reference, current, maximum_bin_count=10, epsilon=1e-6)
        second = population_stability_index(reference, current, maximum_bin_count=10, epsilon=1e-6)
        self.assertTrue(math.isfinite(first["value"]))
        self.assertEqual(first, second)

    def test_performance_maturity_and_degradation(self):
        baseline = {"mae": 10.0, "rmse": 12.0, "wape": 10.0}
        self.assertEqual(evaluate_performance_drift([], baseline, self.policy)["status"], "awaiting_outcomes")
        immature = [{"mature": False, "identityValid": True, "actualOutcome": 100, "pointForecast": 0}]
        self.assertEqual(evaluate_performance_drift(immature, baseline, self.policy)["status"], "awaiting_outcomes")
        too_few = [{"mature": True, "identityValid": True, "actualOutcome": 100, "pointForecast": 90}] * 7
        self.assertEqual(evaluate_performance_drift(too_few, baseline, self.policy)["status"], "insufficient_outcomes")
        stable = [{"mature": True, "identityValid": True, "actualOutcome": 100, "pointForecast": 90}] * 8
        degraded = [{"mature": True, "identityValid": True, "actualOutcome": 100, "pointForecast": 60}] * 8
        self.assertEqual(evaluate_performance_drift(stable, baseline, self.policy)["status"], "stable")
        self.assertEqual(evaluate_performance_drift(degraded, baseline, self.policy)["status"], "material_degradation")
        wrong = copy.deepcopy(stable); wrong[0]["identityValid"] = False
        self.assertEqual(evaluate_performance_drift(wrong, baseline, self.policy)["status"], "identity_mismatch")

    def test_ranking_and_recommendation_never_mutate_assignment(self):
        stable_feature = {"status": "stable"}; stable_performance = {"status": "awaiting_outcomes"}
        ranking = evaluate_ranking_instability("gradient_boosting", None, "gradient_boosting", ["gradient_boosting"], None)
        self.assertEqual(reassessment_recommendation(stable_feature, stable_performance, ranking)["state"], "not_recommended")
        material = reassessment_recommendation({"status": "material_drift"}, stable_performance, ranking)
        self.assertEqual(material["state"], "recommended")
        degraded = reassessment_recommendation(stable_feature, {"status": "material_degradation"}, ranking)
        self.assertEqual(degraded["state"], "recommended")
        changed = evaluate_ranking_instability("gradient_boosting", "poisson_regression", "gradient_boosting",
            ["gradient_boosting", "poisson_regression"], ["poisson_regression", "gradient_boosting"])
        recommendation = reassessment_recommendation(stable_feature, stable_performance, changed)
        self.assertEqual(recommendation["state"], "review_required")
        self.assertFalse(recommendation["automaticReassessmentStarted"])
        self.assertFalse(recommendation["automaticAssignmentAllowed"])

    def test_confidence_is_deterministic_bounded_and_monotone(self):
        first = self.confidence(); second = self.confidence()
        self.assertEqual(first, second)
        self.assertGreaterEqual(first["score"], 0); self.assertLessEqual(first["score"], 100)
        self.assertGreater(first["score"], self.confidence(psi=0.25)["score"])
        self.assertGreaterEqual(self.confidence(width=20)["score"], self.confidence(width=80)["score"])
        self.assertGreaterEqual(self.confidence(data_score=1)["score"], self.confidence(data_score=0.5)["score"])
        small = self.confidence(psi=0.0101)
        self.assertLessEqual(abs(first["score"] - small["score"]), 1)

    def test_performance_is_optional_not_perfect_and_degradation_lowers_confidence(self):
        ex_ante = self.confidence()
        stable = self.confidence(performance={"status": "stable", "maximumDegradationRatio": 1.0})
        degraded = self.confidence(performance={"status": "material_degradation", "maximumDegradationRatio": 1.35})
        self.assertNotIn("performanceScore", ex_ante["components"])
        self.assertAlmostEqual(sum(ex_ante["appliedWeights"].values()), 1.0)
        self.assertGreater(stable["score"], degraded["score"])

    def test_point_only_is_unavailable_and_forecast_values_are_not_inputs(self):
        value = calculate_confidence(calibration={"status": "unavailable", "reason": "calibration_not_available_for_assignment"},
            interval={"status": "unavailable"}, feature_drift={"status": "stable", "maximumValue": 0},
            data_quality={"verified": True, "score": 1}, performance={"status": "awaiting_outcomes"}, policy=self.policy)
        self.assertEqual(value["status"], "unavailable")
        self.assertIsNone(value["score"])

    def test_policy_and_component_tampering_fail_validation(self):
        invalid_weights = copy.deepcopy(self.policy)
        invalid_weights["confidence"]["weights"]["performanceScore"] = 0.5
        invalid_weights["policy_sha256"] = "0" * 64
        with self.assertRaises(GovernedMonitoringError): validate_monitoring_policy(invalid_weights)
        tampered = copy.deepcopy(self.policy)
        tampered["feature_drift"]["material_threshold"] = 9
        with self.assertRaises(GovernedMonitoringError): validate_monitoring_policy(tampered)

    def test_committed_confidence_component_tamper_fails_hash_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);monitoring_id=str(uuid.uuid4());bundle=root/monitoring_id
            (bundle/"artifacts").mkdir(parents=True);(bundle/"metadata").mkdir()
            authority_sha="1"*64
            confidence=self.confidence()
            evidence={"schemaVersion":"1.0","monitoringId":monitoring_id,"deploymentId":"dhaka_south",
                "policy":{"policyId":self.policy["policy_id"],"policyVersion":self.policy["policy_version"],"policySha256":self.policy_sha},
                "authority":{"authoritySnapshotSha256":authority_sha,"assignmentId":str(uuid.uuid4()),"assignmentPointerSha256":"2"*64,"assignmentCommitSha256":"3"*64,
                    "sourceAssessmentId":str(uuid.uuid4()),"sourceAssessmentCommitSha256":"4"*64,"sourceFeatureMatrixSha256":"5"*64,"forecastRunId":str(uuid.uuid4()),
                    "forecastLatestSha256":"6"*64,"forecastCommitSha256":"7"*64,"currentFeatureMatrixSha256":"8"*64,"datasetId":"9"*64,
                    "featureOrderSha256":"a"*64,"calibrationSha256":"b"*64,"uncertaintySha256":"c"*64,"outcomeMonitoringLatestSha256":None,"latestReassessmentCommitSha256":None},
                "featureDrift":{"status":"stable"},"performanceDrift":{"status":"awaiting_outcomes"},"rankingInstability":{"status":"no_new_reassessment"},
                "recommendation":{"state":"not_recommended"},"confidence":confidence,
                "invariants":{"confidenceScoreChangesModelSelection":False,"confidenceAffectsForecastPoint":False,"confidenceAffectsPredictionInterval":False,
                    "confidenceAffectsPreparedness":False,"reassessmentAutoStarted":False,"modelAutoReassigned":False},"generatedAt":"2026-08-02T00:00:00Z"}
            evidence_path=bundle/"artifacts/governed_monitoring.json";evidence_path.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
            evidence_sha=hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            commit={"schemaVersion":"1.0","monitoringId":monitoring_id,"deploymentId":"dhaka_south","policyId":self.policy["policy_id"],
                "policyVersion":self.policy["policy_version"],"policySha256":self.policy_sha,"authoritySnapshotSha256":authority_sha,"evidenceSha256":evidence_sha,
                "status":"committed","committedAt":"2026-08-02T00:00:00Z","assignmentModified":False,"forecastModified":False,"preparednessModified":False}
            (bundle/"metadata/governed_monitoring_commit.json").write_text(json.dumps(commit,indent=2)+"\n",encoding="utf-8")
            self.assertIsNotNone(_verify_existing(bundle,authority_sha,self.policy_sha))
            evidence["confidence"]["components"]["inputStabilityScore"]=0.99
            evidence_path.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf-8")
            with self.assertRaises(Exception):_verify_existing(bundle,authority_sha,self.policy_sha)


if __name__ == "__main__":
    unittest.main()
