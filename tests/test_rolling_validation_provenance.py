from __future__ import annotations
import copy, hashlib, json, sys, unittest
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
from validation_backtest import validate_rolling_validation

class RollingValidationProvenanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = ROOT / "data" / "rolling_validation.json"; cls.raw = cls.path.read_bytes()
        cls.artifact = json.loads(cls.raw); cls.card = json.loads((ROOT / "data" / "model_card.json").read_text())
        cls.frame = pd.read_csv(ROOT / "data" / "model_features.csv")
    def test_exact_hash_and_shared_identity(self):
        digest = hashlib.sha256(self.raw).hexdigest()
        self.assertEqual(self.card["rolling_validation_artifact_sha256"], digest)
        validate_rolling_validation(self.artifact, expected_df=self.frame, expected_provenance=self.card["provenance"], expected_model_card=self.card, expected_artifact_sha256=digest)
        self.assertEqual(self.artifact["provenance"]["run_id"], self.card["provenance"]["run_id"])
    def test_wrong_contract_values_fail(self):
        for key, value in (("fold_count", 67), ("target", "wrong"), ("horizon_weeks", 1), ("feature_names", list(reversed(self.artifact["feature_names"])))):
            altered = copy.deepcopy(self.artifact); altered[key] = value
            with self.assertRaises(ValueError): validate_rolling_validation(altered)
    def test_registry_phase_suffix_and_runtime_binding(self):
        self.assertEqual(self.artifact["formula_registry_version"], "p1.3-v1")
        malformed = copy.deepcopy(self.artifact); malformed["formula_registry_version"] = "not-a-version"
        with self.assertRaises(ValueError): validate_rolling_validation(malformed)
        stale = copy.deepcopy(self.artifact); stale["formula_registry_sha256"] = "0" * 64
        with self.assertRaises(ValueError): validate_rolling_validation(stale)
    def test_stale_matrix_and_altered_hash_fail(self):
        altered = copy.deepcopy(self.artifact); altered["folds"][0]["training_matrix_sha256"] = "0" * 64
        with self.assertRaises(ValueError): validate_rolling_validation(altered, expected_df=self.frame)
        with self.assertRaises(ValueError): validate_rolling_validation(self.artifact, expected_model_card=self.card, expected_artifact_sha256="0" * 64)

if __name__ == "__main__": unittest.main()
