import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
SPEC = importlib.util.spec_from_file_location(
    "runtime_assessment_policy", ROOT / "analytics" / "runtime_assessment_policy.py"
)
runtime_assessment_policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(runtime_assessment_policy)


class RuntimeAssessmentPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, cls.policy_sha = runtime_assessment_policy.load_and_validate_assessment_policy("dhaka_south")
        cls.phase_one_policy, cls.phase_one_policy_sha = runtime_assessment_policy.load_and_validate_assessment_policy(
            "dhaka_south", "p1.4d-1-v1"
        )
        cls.registry_path = ROOT / "config" / "candidate_models.json"
        cls.registry = json.loads(cls.registry_path.read_text(encoding="utf-8"))
        cls.registry_sha = hashlib.sha256(cls.registry_path.read_bytes()).hexdigest()

    def context(self, labelled_rows=173):
        return {
            "validation_passed": True,
            "deployment_id": "dhaka_south",
            "case_geography": {"geography_level": "city", "geography_id": "BGD-DHAKA-SOUTH", "geography_name": "Dhaka South"},
            "climate_geography": {"geography_level": "city", "geography_id": "BGD-DHAKA-SOUTH", "geography_name": "Dhaka South"},
            "canonical_contract_version": "p1.4b-canonical-upload-v1",
            "feature_order_sha256": self.registry["feature_order_sha256"],
            "constructible_feature_count": 18,
            "target": "target_cases_next_2w",
            "horizon_weeks": 2,
            "source_metadata": {
                "cases": {"source_type": "synthetic_benchmark", "aggregation_method": "weekly_epi_week_case_count", "contains_approximated_values": False},
                "climate": {"source_type": "synthetic_benchmark", "aggregation_method": "simulated_weekly_benchmark", "contains_approximated_values": False},
            },
            "labelled_rows": labelled_rows,
            "available_history_weeks": labelled_rows + 7,
            "candidate_registry": copy.deepcopy(self.registry),
            "candidate_registry_sha256": self.registry_sha,
            "chronological_order_valid": True,
            "duplicate_periods_absent": True,
            "contiguous_history": True,
            "case_climate_aligned": True,
        }

    def test_policy_schema_hash_and_repository_bindings(self):
        schema = json.loads((ROOT / "config" / "runtime_assessment_policy.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(self.policy)
        self.assertEqual(self.policy["policy_sha256"], self.policy_sha)
        self.assertEqual(self.policy["deployment_id"], "dhaka_south")
        self.assertEqual(self.policy["geography_scope"]["id"], "BGD-DHAKA-SOUTH")
        self.assertEqual(self.policy["candidate_registry"]["sha256"], self.registry_sha)
        self.assertEqual(self.policy["feature_contract"]["feature_order_sha256"], self.registry["feature_order_sha256"])
        self.assertEqual(self.policy["input_contract"]["target"], self.registry["target"])
        self.assertEqual(self.policy["input_contract"]["horizon_weeks"], 2)
        self.assertEqual(self.policy["policy_version"], "p2-v1")
        self.assertEqual(self.phase_one_policy["policy_version"], "p1.4d-1-v1")
        self.assertEqual(
            self.phase_one_policy_sha,
            "dbf9d4cc4713bbb9d114b2dab916d0f20b3004ac14b37ca663c3caecefcea0af",
        )

    def test_version_resolution_rejects_unknown_or_mismatched_hash(self):
        with self.assertRaises(runtime_assessment_policy.RuntimeAssessmentPolicyError):
            runtime_assessment_policy.load_and_validate_assessment_policy("dhaka_south", "unknown")
        with self.assertRaises(runtime_assessment_policy.RuntimeAssessmentPolicyError):
            runtime_assessment_policy.load_and_validate_assessment_policy(
                "dhaka_south", "p2-v1", expected_sha256="0" * 64
            )

    def test_recommendation_grade_dataset_is_policy_eligible_without_recommendation_strength(self):
        result = runtime_assessment_policy.evaluate_assessment_policy(self.policy, self.context())
        self.assertTrue(result["eligible"])
        self.assertEqual(result["assessmentStatus"], "full_assessment_eligible")
        self.assertEqual(result["availableFoldCount"], 68)
        self.assertEqual(result["plannedFoldCount"], 68)
        self.assertEqual(result["minimumFoldCount"], 52)
        self.assertEqual(result["maximumFoldCount"], 68)
        self.assertFalse(result["foldCapApplied"])
        self.assertEqual(result["selectedValidationStartIndex"], 105)
        self.assertEqual(result["selectedValidationEndIndex"], 172)
        self.assertEqual(result["decisionCompatibilityStatus"], "phase2_decision_policy_not_yet_available")
        self.assertEqual(result["candidateSetStatus"], "complete_candidate_set")
        self.assertTrue(all(value["eligible"] for value in result["candidateEligibility"].values()))
        self.assertFalse(result["recommendationEligibility"])
        self.assertEqual(result["recommendationStatus"], "evidence_only")
        self.assertEqual(result["recommendationStrength"], "not_available")
        self.assertTrue(result["approvalRequired"])
        self.assertFalse(result["approvalEnabled"])

    def test_dynamic_minimum_and_recent_cap(self):
        for labelled_rows, available, planned, start, capped in (
            (156, 51, 0, None, False),
            (157, 52, 52, 105, False),
            (172, 67, 67, 105, False),
            (174, 69, 68, 106, True),
            (250, 145, 68, 182, True),
        ):
            with self.subTest(labelled_rows=labelled_rows):
                result = runtime_assessment_policy.evaluate_assessment_policy(self.policy, self.context(labelled_rows))
                self.assertEqual(result["availableFoldCount"], available)
                self.assertEqual(result["plannedFoldCount"], planned)
                self.assertEqual(result["selectedValidationStartIndex"], start)
                self.assertEqual(result["foldCapApplied"], capped)
                self.assertEqual(result["eligible"], labelled_rows >= 157)

    def test_phase_one_exact_row_contract_remains_archived(self):
        short = runtime_assessment_policy.evaluate_assessment_policy(self.phase_one_policy, self.context(172))
        exact = runtime_assessment_policy.evaluate_assessment_policy(self.phase_one_policy, self.context(173))
        long = runtime_assessment_policy.evaluate_assessment_policy(self.phase_one_policy, self.context(174))
        self.assertEqual(short["assessmentStatus"], "insufficient_history")
        self.assertTrue(exact["eligible"])
        self.assertEqual(long["assessmentStatus"], "assessment_blocked")
        self.assertIn("fold_cap_governance_pending", long["reasonCodes"])

    def test_deployment_geography_source_and_contract_failures_block(self):
        mutations = [
            (lambda c: c.update(deployment_id="other"), "deployment_mismatch"),
            (lambda c: c["case_geography"].update(geography_id="BGD-OTHER"), "geography_mismatch"),
            (lambda c: c["source_metadata"]["climate"].update(source_type="observed"), "source_scope_mismatch"),
            (lambda c: c.update(canonical_contract_version="other"), "canonical_contract_mismatch"),
            (lambda c: c.update(feature_order_sha256="0" * 64), "feature_contract_mismatch"),
            (lambda c: c.update(target="other"), "target_mismatch"),
            (lambda c: c.update(horizon_weeks=1), "horizon_mismatch"),
            (lambda c: c.update(contiguous_history=False), "non_contiguous_history"),
        ]
        for mutation, code in mutations:
            with self.subTest(code=code):
                context = self.context()
                mutation(context)
                result = runtime_assessment_policy.evaluate_assessment_policy(self.policy, context)
                self.assertFalse(result["eligible"])
                self.assertIn(code, result["reasonCodes"])

    def test_candidate_registry_and_parameter_identity_fail_closed(self):
        context = self.context()
        context["candidate_registry_sha256"] = "0" * 64
        result = runtime_assessment_policy.evaluate_assessment_policy(self.policy, context)
        self.assertFalse(result["eligible"])
        self.assertIn("candidate_registry_mismatch", result["reasonCodes"])
        self.assertTrue(all(not value["eligible"] for value in result["candidateEligibility"].values()))

        context = self.context()
        context["candidate_prerequisites"] = {"random_forest": {"parameters_sha256": "0" * 64}}
        result = runtime_assessment_policy.evaluate_assessment_policy(self.policy, context)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["candidateSetStatus"], "partial_candidate_set")
        self.assertFalse(result["candidateEligibility"]["random_forest"]["eligible"])

    def test_baseline_and_learned_model_breadth_are_required(self):
        baseline_ids = ["previous_week_naive", "moving_average_4w", "seasonal_naive_52w"]
        learned_ids = ["ridge_regression", "poisson_regression", "random_forest", "gradient_boosting"]
        for ids, code in ((baseline_ids, "no_eligible_baseline"), (learned_ids, "no_eligible_learned_model")):
            with self.subTest(code=code):
                context = self.context()
                context["candidate_prerequisites"] = {model_id: {"fold_plan_compatible": False} for model_id in ids}
                result = runtime_assessment_policy.evaluate_assessment_policy(self.policy, context)
                self.assertFalse(result["eligible"])
                self.assertEqual(result["candidateSetStatus"], "insufficient_candidate_breadth")
                self.assertIn(code, result["reasonCodes"])

    def test_policy_evaluator_has_no_analytics_or_side_effects(self):
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        runtime_assessment_policy.evaluate_assessment_policy(self.policy, self.context())
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        self.assertEqual(before, after)
        source = (ROOT / "analytics" / "runtime_assessment_policy.py").read_text(encoding="utf-8")
        for forbidden in (".fit(", ".predict(", "generate_rolling_fold_descriptors", "build_candidate_comparison", "build_directives"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
