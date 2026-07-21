import json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class AuthorizationTests(unittest.TestCase):
 def test_one_run_append_only_contract(self):
  policy=json.loads((ROOT/'config/deployments/dhaka_south/decision_policy.json').read_text());self.assertEqual(policy['authorizationPolicy']['scope'],'one_run');self.assertTrue(policy['authorizationPolicy']['oneRunPerAuthorization']);self.assertTrue(policy['authorizationPolicy']['oneReservationPerAuthorization']);self.assertFalse(policy['authorizationPolicy']['automaticRetryAllowed']);event=json.loads((ROOT/'config/runtime_authorization_event.schema.json').read_text());self.assertEqual(event['properties']['eventType']['enum'],['reserved','consumed'])
 def test_authorization_schema_has_disjoint_historical_and_phase_two_branches(self):
  schema=json.loads((ROOT/'config/runtime_forecast_authorization.schema.json').read_text());self.assertEqual(len(schema['oneOf']),3);self.assertEqual(schema['$defs']['phase1']['properties']['schemaVersion']['const'],'1.0');self.assertEqual(schema['$defs']['phase2v1']['properties']['schemaVersion']['const'],'2.0');self.assertEqual(schema['$defs']['phase2v2']['properties']['schemaVersion']['const'],'2.0');self.assertIn('assessmentPlannedFoldCount',schema['$defs']['phase2v2']['required']);self.assertNotIn('assessmentPlannedFoldCount',schema['$defs']['phase1']['properties'])
if __name__=='__main__':unittest.main()
