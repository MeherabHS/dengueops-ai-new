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
        self.assertEqual(policy["policy_version"],"p1.4g-v1")
        self.assertEqual(digest,policy["policy_sha256"])
        self.assertEqual(digest,canonical_policy_sha256(policy))
        self.assertEqual(policy["forecast_scope"]["required_policy_version"],"p1.4f-v1")
        self.assertFalse(policy["duplicate_rule"]["corrections_allowed"])
        self.assertIn("forecast_latest_pointer_update",policy["prohibited_actions"])

    def test_unknown_deployment_fails_closed(self):
        with self.assertRaises(ValueError):load_and_validate_forecast_outcome_policy("other")

if __name__=="__main__":unittest.main()
