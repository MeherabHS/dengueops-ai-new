import json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AuthorizationTests(unittest.TestCase):
 def test_one_run_append_only_contract(self):
  policy=json.loads((ROOT/'config/deployments/dhaka_south/decision_policy.json').read_text());self.assertEqual(policy['authorizationPolicy']['scope'],'one_run');self.assertTrue(policy['authorizationPolicy']['oneRunPerAuthorization']);self.assertFalse(policy['authorizationPolicy']['automaticRetryAllowed']);event=json.loads((ROOT/'config/runtime_authorization_event.schema.json').read_text());self.assertEqual(event['properties']['eventType']['enum'],['reserved','consumed'])
if __name__=='__main__':unittest.main()
