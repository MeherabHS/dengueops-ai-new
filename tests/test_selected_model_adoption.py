import copy, hashlib, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
from deployment_profiles import load_deployment_profile
from forecast_model import validate_selected_model_adoption
from model_factory import build_candidate_estimator, load_and_validate_candidate_registry
from provenance import provenance_from_feature_frame
from validation_backtest import load_feature_matrix


class SelectedModelAdoptionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry, cls.registry_hash = load_and_validate_candidate_registry(ROOT / "config/candidate_models_p1.2a-v1.json")
        cls.comparison_bytes = (ROOT / "data/candidate_model_comparison.json").read_bytes()
        cls.comparison = json.loads(cls.comparison_bytes)
        cls.rolling_bytes = (ROOT / "data/rolling_validation.json").read_bytes()
        cls.rolling = json.loads(cls.rolling_bytes)
        cls.profile = load_deployment_profile("dhaka_south")
        cls.frame = load_feature_matrix()
        cls.provenance = provenance_from_feature_frame(cls.frame)

    def validate(self, comparison):
        return validate_selected_model_adoption(
            comparison, hashlib.sha256(self.comparison_bytes).hexdigest(), self.rolling,
            hashlib.sha256(self.rolling_bytes).hexdigest(), self.registry, self.registry_hash,
            self.profile, self.provenance,
        )

    def test_winner_is_independently_validated(self):
        candidate = self.validate(self.comparison)
        self.assertEqual(candidate["model_id"], "random_forest")
        self.assertEqual(self.comparison["aggregate_metrics"]["random_forest"]["successful_folds"], 68)
        self.assertEqual(self.comparison["aggregate_metrics"]["random_forest"]["failed_folds"], 0)

    def test_mutated_winner_and_hash_are_blocked(self):
        for key, value in (("comparison_selected_model", "gradient_boosting"),
                           ("candidate_registry_sha256", "0" * 64),
                           ("selected_model_parameters_sha256", "0" * 64)):
            mutated = copy.deepcopy(self.comparison); mutated[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): self.validate(mutated)

    def test_factory_is_registry_driven_and_has_no_fallback(self):
        first = build_candidate_estimator("random_forest", self.registry)
        second = build_candidate_estimator("random_forest", self.registry)
        self.assertIsNot(first, second)
        self.assertEqual(first.get_params()["n_estimators"], 200)
        self.assertNotIn("scaler", getattr(first, "named_steps", {}))
        for model_id in ("gradient_boosting", "ridge_regression", "poisson_regression"):
            self.assertIsNotNone(build_candidate_estimator(model_id, self.registry))
        with self.assertRaises(ValueError): build_candidate_estimator("unsupported", self.registry)


if __name__ == "__main__": unittest.main()
