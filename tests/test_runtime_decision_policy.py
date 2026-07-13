import hashlib,json,unittest
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
class DecisionPolicyTests(unittest.TestCase):
 def test_policy_hash_scope_and_prohibitions(self):
  policy=json.loads((ROOT/'config/deployments/dhaka_south/decision_policy.json').read_text());schema=json.loads((ROOT/'config/runtime_decision_policy.schema.json').read_text());Draft202012Validator(schema).validate(policy);expected=policy.pop('policySha256');digest=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest();self.assertEqual(digest,expected);self.assertEqual(policy['decisionScope'],'one_run');self.assertEqual(policy['recommendationStatusAccepted'],'evidence_only');self.assertEqual(policy['recommendationStrengthAccepted'],'not_available');self.assertFalse(policy['baselineApprovalAllowed']);self.assertFalse(policy['deploymentWideAdoptionAllowed'])
if __name__=='__main__':unittest.main()
