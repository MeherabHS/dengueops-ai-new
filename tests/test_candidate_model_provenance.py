from __future__ import annotations
import copy, hashlib, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"analytics"))
from model_candidates import REGISTRY_PATH, ROLLING_PATH, validate_comparison_artifact

class CandidateProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path=ROOT/"data/candidate_model_comparison.json"; cls.raw=cls.path.read_bytes(); cls.artifact=json.loads(cls.raw); cls.card=json.loads((ROOT/"data/model_card.json").read_text())
    def test_exact_hashes_and_shared_provenance(self):
        digest=hashlib.sha256(self.raw).hexdigest(); self.assertEqual(self.card["candidate_model_comparison_artifact_sha256"],digest)
        validate_comparison_artifact(self.artifact,expected_registry_sha256=hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest(),expected_rolling_sha256=hashlib.sha256(ROLLING_PATH.read_bytes()).hexdigest(),expected_model_card=self.card,expected_artifact_sha256=digest)
        self.assertEqual(self.artifact["provenance"],self.card["provenance"])
    def test_altered_registry_rolling_and_comparison_fail(self):
        with self.assertRaises(ValueError): validate_comparison_artifact(self.artifact,expected_registry_sha256="0"*64)
        with self.assertRaises(ValueError): validate_comparison_artifact(self.artifact,expected_rolling_sha256="0"*64)
        with self.assertRaises(ValueError): validate_comparison_artifact(self.artifact,expected_model_card=self.card,expected_artifact_sha256="0"*64)
        altered=copy.deepcopy(self.artifact); altered["fold_references"][0]["training_matrix_sha256"]="0"*64
        rolling=json.loads(ROLLING_PATH.read_text())
        with self.assertRaises(ValueError): validate_comparison_artifact(altered,expected_rolling=rolling)
    def test_active_forecast_is_rf_and_legacy_explainability_remains_gbr(self):
        forecast=json.loads((ROOT/"data/forecast_output.json").read_text()); explain=json.loads((ROOT/"data/model_explainability.json").read_text())
        self.assertEqual((forecast["target_epi_year"],forecast["target_epi_week"]),(2024,26))
        self.assertEqual(explain["estimator_family"],"GradientBoostingRegressor"); self.assertFalse(explain["active_model_evidence"])
        self.assertEqual(self.card["current_forecast_model"],"random_forest")
        self.assertEqual(forecast["forecast_uncertainty"]["active_model_id"],"random_forest")
        self.assertEqual(forecast["preparedness_scenario_method"]["model"],"RandomForestRegressor")
if __name__=="__main__": unittest.main()
