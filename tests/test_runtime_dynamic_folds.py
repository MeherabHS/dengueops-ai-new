import importlib.util
import json
import sys
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
SPEC = importlib.util.spec_from_file_location("runtime_assessment_policy", ROOT / "analytics" / "runtime_assessment_policy.py")
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(module)


class RuntimeDynamicFoldPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, _ = module.load_and_validate_assessment_policy("dhaka_south")
        cls.phase_one_policy, _ = module.load_and_validate_assessment_policy("dhaka_south", "p1.4d-1-v1")
        cls.fold = cls.policy["fold_policy"]

    def test_dynamic_count_preserves_governed_chronology_parameters(self):
        self.assertEqual(module.available_fold_count(173, self.fold), 68)
        self.assertEqual(module.available_fold_count(172, self.fold), 67)
        self.assertEqual(module.available_fold_count(174, self.fold), 69)
        self.assertEqual(module.available_fold_count(105, self.fold), 0)
        self.assertEqual(module.available_fold_count(106, self.fold), 1)
        self.assertEqual(self.fold["initial_training_rows"], 104)
        self.assertEqual(self.fold["embargo_rows"], 1)
        self.assertEqual(self.fold["step_size_weeks"], 1)
        self.assertTrue(self.fold["same_precomputed_plan_for_all_candidates"])
        self.assertFalse(self.fold["candidate_outcomes_may_change_plan"])

    def test_phase_one_shorter_and_longer_history_remain_blocked(self):
        from tests.test_runtime_assessment_policy import RuntimeAssessmentPolicyTests
        helper = RuntimeAssessmentPolicyTests()
        helper.policy = self.phase_one_policy
        helper.registry_path = ROOT / "config" / "candidate_models.json"
        helper.registry = json.loads(helper.registry_path.read_text(encoding="utf-8"))
        import hashlib
        helper.registry_sha = hashlib.sha256(helper.registry_path.read_bytes()).hexdigest()
        short = module.evaluate_assessment_policy(self.phase_one_policy, helper.context(172))
        self.assertEqual(short["assessmentStatus"], "insufficient_history")
        self.assertEqual(short["availableFoldCount"], 67)
        self.assertEqual(short["plannedFoldCount"], 67)
        long = module.evaluate_assessment_policy(self.phase_one_policy, helper.context(174))
        self.assertEqual(long["assessmentStatus"], "assessment_blocked")
        self.assertEqual(long["availableFoldCount"], 69)
        self.assertEqual(long["plannedFoldCount"], 0)
        self.assertIn("fold_cap_governance_pending", long["reasonCodes"])

    def test_phase_two_accepts_minimum_and_caps_recent_folds(self):
        indexes = module.select_planned_validation_indexes(157, 104, 1, 52, 68)
        self.assertEqual(indexes, tuple(range(105, 157)))
        self.assertEqual(module.select_planned_validation_indexes(172, 104, 1, 52, 68), tuple(range(105, 172)))
        self.assertEqual(module.select_planned_validation_indexes(174, 104, 1, 52, 68), tuple(range(106, 174)))
        self.assertEqual(module.select_planned_validation_indexes(250, 104, 1, 52, 68), tuple(range(182, 250)))
        with self.assertRaises(module.RuntimeAssessmentPolicyError):
            module.select_planned_validation_indexes(156, 104, 1, 52, 68)

    def test_runtime_rolling_schema_binds_current_governed_execution_depth(self):
        schema = json.loads((ROOT / "config" / "runtime_rolling_validation.schema.json").read_text(encoding="utf-8"))
        phase_one, phase_two = schema["oneOf"]
        self.assertEqual(phase_one["properties"]["plannedFoldCount"]["const"], 68)
        self.assertEqual(phase_one["properties"]["folds"]["minItems"], 68)
        self.assertEqual(phase_one["properties"]["folds"]["maxItems"], 68)
        self.assertEqual(phase_two["properties"]["folds"]["minItems"], 52)
        self.assertEqual(phase_two["properties"]["folds"]["maxItems"], 68)
        self.assertEqual(len(phase_two["properties"]["candidateIds"]["const"]), 7)
        self.assertFalse(phase_one["additionalProperties"])
        self.assertFalse(phase_two["additionalProperties"])

    def test_candidate_failure_policy_never_shrinks_fold_plan(self):
        candidate_policy = self.policy["candidate_eligibility_policy"]
        self.assertFalse(candidate_policy["failed_candidate_may_shrink_common_folds"])
        self.assertTrue(candidate_policy["eligible_candidates_must_use_every_planned_fold"])
        self.assertTrue(all(candidate["failure_policy"] == "failed_fold_excludes_candidate_from_selection_without_changing_fold_plan" for candidate in candidate_policy["candidates"]))


if __name__ == "__main__":
    unittest.main()
