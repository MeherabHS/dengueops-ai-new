import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"analytics"))
from runtime_model_degradation_policy import *
class ModelDegradationPolicyTests(unittest.TestCase):
    def test_identity_hash_and_disabled_boundaries(self):
        policy,digest=load_and_validate_model_degradation_policy();self.assertEqual((policy["policy_id"],policy["policy_version"],digest),(POLICY_ID,POLICY_VERSION,POLICY_SHA));self.assertIsNone(policy["monitoring_window"]["windowOutcomeCount"]);self.assertIsNone(policy["degradationThresholds"]);self.assertFalse(policy["materialWorseningClassificationAllowed"]);self.assertFalse(policy["lifecycleRecommendationAllowed"])
    def test_unknown_identity_rejected(self):
        for args in (("other","1.0","p2-v1"),("dhaka_south","1.0","unknown"),("dhaka_south","2.0","p2-v1")):
            with self.assertRaises(ModelDegradationPolicyError):load_and_validate_model_degradation_policy(*args)
if __name__=="__main__":unittest.main()
