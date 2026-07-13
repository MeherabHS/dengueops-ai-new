import json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class RuntimeDecisionTests(unittest.TestCase):
 def test_client_cannot_supply_model_or_hashes(self):
  source=(ROOT/'app/api/runtime/assessments/[assessmentId]/decisions/route.ts').read_text();self.assertIn('unsupported fields',source);self.assertIn('timingSafeEqual',source);self.assertNotIn('selectedModelId: body',source);self.assertNotIn('selectedModelParameterSha256: body',source)
 def test_baselines_are_not_authorized(self):
  policy=json.loads((ROOT/'config/deployments/dhaka_south/decision_policy.json').read_text());self.assertEqual(policy['allowedDeployableCandidateClasses'],['deployable_learned_model']);self.assertFalse(policy['baselineApprovalAllowed'])
if __name__=='__main__':unittest.main()
