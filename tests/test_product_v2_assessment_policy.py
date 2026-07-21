from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_assessment_policy import load_and_validate_assessment_policy


class ProductV2AssessmentPolicyTests(unittest.TestCase):
    def test_active_policy_is_p2_v2_and_binds_exact_v2_registry(self):
        policy, digest = load_and_validate_assessment_policy("dhaka_south", "p2-v2")
        self.assertEqual(policy["policy_sha256"], digest)
        self.assertEqual(policy["candidate_registry"]["version"], "p2-v1")
        candidates = policy["candidate_eligibility_policy"]["candidates"]
        self.assertEqual(len(candidates), 10)
        self.assertEqual(sum(c["candidate_class"] == "learned_model" for c in candidates), 8)
        self.assertEqual(sum(c["candidate_class"] == "comparison_baseline" for c in candidates), 2)
        self.assertTrue(policy["fold_policy"]["same_precomputed_plan_for_all_candidates"])
        self.assertFalse(policy["fold_policy"]["candidate_outcomes_may_change_plan"])
        self.assertIn("eligible learned", policy["comparison_policy"]["selection_rule"].lower())

    def test_historical_p2_v1_policy_loads_from_archive(self):
        policy, digest = load_and_validate_assessment_policy("dhaka_south", "p2-v1")
        self.assertEqual(policy["policy_version"], "p2-v1")
        self.assertEqual(digest, "04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff")
        self.assertEqual(policy["candidate_registry"]["version"], "p1.2a-v1")


if __name__ == "__main__":
    unittest.main()
