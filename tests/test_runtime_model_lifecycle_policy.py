import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"analytics"))
from runtime_model_lifecycle_policy import *
class LifecyclePolicyTests(unittest.TestCase):
 def test_hash_and_boundaries(self):
  p,h=load_model_lifecycle_policy();self.assertEqual(h,POLICY_SHA256);self.assertFalse(p["automaticPromotionAllowed"]);self.assertFalse(p["automaticRollbackAllowed"]);self.assertFalse(p["nonRandomForestActivationAllowed"]);self.assertEqual(p["permitted_active_model"]["model_id"],"random_forest")
 def test_unknown_rejected(self):
  with self.assertRaises(ModelLifecyclePolicyError):load_model_lifecycle_policy(version="unknown")
if __name__=="__main__":unittest.main()
