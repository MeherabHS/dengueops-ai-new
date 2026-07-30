import copy,json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"analytics"))
import runtime_model_degradation_policy as policy_module
from runtime_model_degradation_policy import *
class ModelDegradationPolicyTests(unittest.TestCase):
    def test_identity_hash_and_disabled_boundaries(self):
        policy,digest=load_and_validate_model_degradation_policy();self.assertEqual((policy["policy_id"],policy["policy_version"],digest),(POLICY_ID,POLICY_VERSION,POLICY_SHA));self.assertIsNone(policy["monitoring_window"]["windowOutcomeCount"]);self.assertIsNone(policy["degradationThresholds"]);self.assertFalse(policy["materialWorseningClassificationAllowed"]);self.assertFalse(policy["lifecycleRecommendationAllowed"]);self.assertFalse(policy["lifecycleActionProduced"])
    def test_unknown_identity_rejected(self):
        for args in (("other","1.0","p2-v1"),("dhaka_south","1.0","unknown"),("dhaka_south","2.0","p2-v1")):
            with self.assertRaises(ModelDegradationPolicyError):load_and_validate_model_degradation_policy(*args)
    def test_historical_policy_identity_remains_available(self):
        policy,digest=load_and_validate_model_degradation_policy("dhaka_south","1.0","p2-v1")
        self.assertEqual(policy["policy_version"],"p2-v1")
        self.assertEqual(digest,HISTORICAL_POLICY_SHA)
        self.assertEqual(policy["accepted_monitoring_policy"]["policy_version"],"p2-v1")
    def test_p2_v3_current_sources_and_modified_bytes(self):
        policy,digest=load_and_validate_model_degradation_policy()
        self.assertEqual(policy["accepted_monitoring_policy"]["policy_version"],"p2-v3")
        self.assertIn("quick_forecast_p2",policy["accepted_source_families"])
        self.assertEqual(digest,canonical_policy_sha256(policy))
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            target=root/"config/deployments/dhaka_south";target.mkdir(parents=True)
            altered=copy.deepcopy(policy);altered["maturity_statement"]+=" altered"
            (target/"model_degradation_evidence_policy.json").write_text(json.dumps(altered),encoding="utf-8")
            schema_target=root/"config/runtime_model_degradation_evidence_policy.schema.json"
            schema_target.write_bytes((ROOT/"config/runtime_model_degradation_evidence_policy.schema.json").read_bytes())
            previous=policy_module.ROOT
            try:
                policy_module.ROOT=root
                with self.assertRaises(ModelDegradationPolicyError):
                    load_and_validate_model_degradation_policy()
            finally:
                policy_module.ROOT=previous
if __name__=="__main__":unittest.main()
