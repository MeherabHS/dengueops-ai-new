import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/"analytics"))
from runtime_forecast_outcome_policy import canonical_policy_sha256, load_and_validate_forecast_outcome_policy

class ForecastOutcomePolicyTests(unittest.TestCase):
    def test_policy_identity_and_governed_bindings(self):
        policy,digest=load_and_validate_forecast_outcome_policy("dhaka_south")
        self.assertEqual(policy["policy_id"],"RUNTIME.FORECAST_OUTCOME.MONITORING")
        self.assertEqual((policy["schema_version"],policy["policy_version"]),("2.1","p2-v3"))
        self.assertEqual(digest,policy["policy_sha256"])
        self.assertEqual(digest,canonical_policy_sha256(policy))
        self.assertEqual(set(policy["source_families"]),{"quick_forecast_p1","quick_forecast_p2","approved_forecast_p1","approved_forecast_p2"})
        quick=policy["source_families"]["quick_forecast_p2"]
        self.assertEqual((quick["commit_schema_version"],quick["forecast_schema_version"]),("2.1","2.1"))
        self.assertTrue(quick["assignment_provenance_required"]);self.assertTrue(quick["run_record_sha256_required"])
        self.assertFalse(policy["duplicate_rule"]["corrections_allowed"])
        self.assertIn("forecast_latest_pointer_update",policy["prohibited_actions"])

    def test_unknown_deployment_fails_closed(self):
        with self.assertRaises(ValueError):load_and_validate_forecast_outcome_policy("other")

    def test_archived_phase_one_is_version_routed(self):
        policy,digest=load_and_validate_forecast_outcome_policy("dhaka_south","1.0","p1.4g-v1","0121c2fad28b7b8e9080df52698593d1cab677febf4fa668e11f6f19541fb249")
        self.assertEqual((policy["policy_version"],digest),("p1.4g-v1","0121c2fad28b7b8e9080df52698593d1cab677febf4fa668e11f6f19541fb249"))
        with self.assertRaises(ValueError):load_and_validate_forecast_outcome_policy("dhaka_south","1.0","p2-v1")

    def test_archived_p2_v1_is_version_routed_and_unchanged(self):
        policy,digest=load_and_validate_forecast_outcome_policy("dhaka_south","2.0","p2-v1","c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab")
        self.assertEqual((policy["schema_version"],policy["policy_version"]),("2.0","p2-v1"))
        self.assertNotIn("quick_forecast_p2",policy["source_families"])
        self.assertEqual(digest,"c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab")

if __name__=="__main__":unittest.main()
