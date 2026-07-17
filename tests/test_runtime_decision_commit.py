import json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class DecisionCommitTests(unittest.TestCase):
 def test_decision_commit_cannot_update_latest_or_profile(self):
  schema=json.loads((ROOT/'config/runtime_decision_commit.schema.json').read_text());self.assertEqual(len(schema['oneOf']),2)
  for name in ('phase1','phase2'):
   props=schema['$defs'][name]['properties'];self.assertEqual(props['latestPointerUpdated']['const'],False);self.assertEqual(props['deploymentProfileModified']['const'],False)
if __name__=='__main__':unittest.main()
