import json
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]


class RuntimeRecommendationGovernanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads((ROOT / "config" / "deployments" / "dhaka_south" / "assessment_policy.json").read_text(encoding="utf-8"))

    def test_comparison_is_mae_first_with_deterministic_unweighted_ties(self):
        comparison = self.policy["comparison_policy"]
        self.assertEqual(comparison["primary_metric"], "mae")
        self.assertEqual(comparison["tie_sequence"], ["rmse", "wape", "median_absolute_error", "maximum_absolute_error", "selection_complexity_rank", "model_id"])
        self.assertEqual(comparison["tie_tolerance"], 1e-9)
        self.assertFalse(comparison["weighted_aggregate_score_allowed"])
        self.assertFalse(comparison["client_metric_weights_allowed"])
        self.assertFalse(comparison["current_active_model_preference_allowed"])
        self.assertTrue(comparison["selection_requires_all_planned_folds"])
        self.assertFalse(comparison["intersection_only_successful_folds_allowed"])

    def test_strength_thresholds_are_not_fabricated(self):
        recommendation = self.policy["recommendation_policy"]
        self.assertEqual(recommendation["strength_threshold_status"], "not_governed")
        self.assertIsNone(recommendation["strength_thresholds"])
        self.assertEqual(recommendation["technical_winner_without_thresholds"], "evidence_only")
        self.assertEqual(recommendation["strength_without_thresholds"], "not_available")
        self.assertFalse(recommendation["approval_enabled_without_thresholds"])
        self.assertFalse(recommendation["automatic_adoption_allowed"])

    def test_no_recommendation_and_baseline_winner_rules_are_explicit(self):
        recommendation = self.policy["recommendation_policy"]
        conditions = set(recommendation["no_recommendation_conditions"])
        for required in ("insufficient_recommendation_grade_history", "fewer_than_two_eligible_candidates", "no_eligible_naive_baseline", "no_eligible_deployable_learned_model", "no_candidate_completes_all_planned_folds", "unresolved_metric_tie", "policy_inactive", "candidate_registry_mismatch", "fold_policy_mismatch"):
            self.assertIn(required, conditions)
        self.assertEqual(recommendation["baseline_winner_behavior"]["recommendation_status"], "evidence_only")
        self.assertFalse(recommendation["baseline_winner_behavior"]["approval_enabled"])

    def test_runtime_recommendation_schema_supports_evidence_only_without_adoption(self):
        schema = json.loads((ROOT / "config" / "runtime_recommendation.schema.json").read_text(encoding="utf-8"))
        value = {
            "schemaVersion": "1.0", "assessmentId": "11111111-1111-4111-8111-111111111111", "jobId": "22222222-2222-4222-8222-222222222222", "workspaceId": "33333333-3333-4333-8333-333333333333", "datasetId": "a" * 64, "deploymentId": "dhaka_south",
            "assessmentPolicySha256": "b" * 64, "comparisonSha256": "c" * 64, "foldPlanSha256": "d" * 64, "candidateRegistrySha256": "e" * 64,
            "recommendationPolicy": {"policyId": "RUNTIME.ASSESSMENT.RECOMMENDATION_STRENGTH", "policyVersion": "p1.4d-1-v1", "strengthThresholdStatus": "not_governed"},
            "technicalWinnerModelId": "random_forest", "winnerParameterSha256": "f" * 64, "recommendationStatus": "evidence_only", "recommendationStrength": "not_available",
            "recommendationReason": "Technical comparison winner only; strength thresholds are not governed.",
            "candidateSetStatus": "complete_candidate_set", "baselineRequirementSatisfied": True, "learnedModelRequirementSatisfied": True,
            "evidenceInputs": {"winnerMae": 1.0, "runnerUpMae": 2.0, "absoluteMaeGap": 1.0, "relativeMaeGap": 0.5, "successfulFoldRatio": 1.0, "failedFoldCount": 0, "clippingCount": 0, "warningCount": 0, "candidateBreadth": 7, "tieBreakStageUsed": "mae", "datasetFoldCount": 68},
            "limitations": ["No automatic adoption."], "approvalRequired": True, "approvalEnabled": False, "approvalStatus": "approval_pending", "adoptionStatus": "not_adopted",
            "automaticAdoptionAllowed": False, "generatedAt": "2026-07-13T00:00:00Z"
        }
        jsonschema.Draft202012Validator(schema).validate(value)
        value["automaticAdoptionAllowed"] = True
        self.assertTrue(list(jsonschema.Draft202012Validator(schema).iter_errors(value)))


if __name__ == "__main__":
    unittest.main()
