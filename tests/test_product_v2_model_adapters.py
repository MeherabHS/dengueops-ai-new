from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from model_factory import build_candidate_estimator, load_and_validate_candidate_registry
from statsmodels_negative_binomial import StatsmodelsNegativeBinomialNB2


class ProductV2ModelAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry, _ = load_and_validate_candidate_registry()
        rng = np.random.default_rng(90210)
        cls.x = rng.normal(size=(140, 18))
        mean = np.exp(1.2 + 0.08 * cls.x[:, 0] - 0.05 * cls.x[:, 1])
        cls.y = rng.negative_binomial(2.0, 2.0 / (2.0 + mean)).astype(float)

    def test_all_eight_learned_estimators_are_deterministic(self):
        ids = [c["model_id"] for c in self.registry["candidates"] if c["candidate_class"] == "learned_model"]
        self.assertEqual(len(ids), 8)
        for model_id in ids:
            with self.subTest(model_id=model_id):
                first = build_candidate_estimator(model_id, self.registry).fit(self.x, self.y)
                second = build_candidate_estimator(model_id, self.registry).fit(self.x, self.y)
                one = np.asarray(first.predict(self.x[-5:]), dtype=float)
                two = np.asarray(second.predict(self.x[-5:]), dtype=float)
                self.assertEqual(one.shape, (5,))
                self.assertTrue(np.isfinite(one).all())
                np.testing.assert_allclose(one, two, rtol=0, atol=1e-10)

    def test_training_only_scalers_are_owned_by_estimators(self):
        for model_id in ("ridge_regression", "poisson_regression", "elastic_net"):
            estimator = build_candidate_estimator(model_id, self.registry)
            self.assertIsInstance(estimator, Pipeline)
            estimator.fit(self.x[:-7], self.y[:-7])
            np.testing.assert_allclose(estimator.named_steps["scaler"].mean_, self.x[:-7].mean(axis=0))
        nb = build_candidate_estimator("negative_binomial_regression", self.registry).fit(self.x[:-7], self.y[:-7])
        np.testing.assert_allclose(nb.scaler_.mean_, self.x[:-7].mean(axis=0))

    def test_negative_binomial_records_convergence_and_dispersion(self):
        model = StatsmodelsNegativeBinomialNB2().fit(self.x, self.y)
        self.assertTrue(model.fit_evidence_["converged"])
        self.assertGreater(model.fit_evidence_["dispersion"], 0)
        self.assertEqual(model.fit_evidence_["distribution"], "NB2")

    def test_negative_binomial_failures_do_not_fallback(self):
        result = Mock()
        result.params = np.ones(20)
        result.mle_retvals = {"converged": False}
        fake = Mock()
        fake.fit.return_value = result
        with patch("statsmodels_negative_binomial.NegativeBinomial", return_value=fake):
            with self.assertRaisesRegex(ValueError, "converge"):
                StatsmodelsNegativeBinomialNB2().fit(self.x, self.y)

        result.mle_retvals = {"converged": True}
        result.params = np.r_[np.ones(19), -1.0]
        with patch("statsmodels_negative_binomial.NegativeBinomial", return_value=fake):
            with self.assertRaisesRegex(ValueError, "dispersion"):
                StatsmodelsNegativeBinomialNB2().fit(self.x, self.y)

        result.params = np.r_[np.ones(19), 1.0]
        fake.fit.side_effect = lambda **_: (warnings.warn("did not converge", RuntimeWarning), result)[1]
        with patch("statsmodels_negative_binomial.NegativeBinomial", return_value=fake):
            with self.assertRaisesRegex(ValueError, "warning"):
                StatsmodelsNegativeBinomialNB2().fit(self.x, self.y)

    def test_negative_binomial_rejects_nonfinite_parameters_and_predictions(self):
        model = StatsmodelsNegativeBinomialNB2().fit(self.x, self.y)
        model.result_.predict = Mock(return_value=np.array([np.nan]))
        with self.assertRaisesRegex(ValueError, "finite"):
            model.predict(self.x[:1])
        model.result_.predict = Mock(return_value=np.array([-1.0]))
        with self.assertRaisesRegex(ValueError, "negative"):
            model.predict(self.x[:1])

    def test_negative_binomial_rejects_singular_and_nonfinite_fits(self):
        fake = Mock()
        fake.fit.side_effect = np.linalg.LinAlgError("singular")
        with patch("statsmodels_negative_binomial.NegativeBinomial", return_value=fake):
            with self.assertRaisesRegex(ValueError, "fit failed"):
                StatsmodelsNegativeBinomialNB2().fit(self.x, self.y)
        result = Mock(params=np.r_[np.ones(18), np.nan, 1.0], mle_retvals={"converged": True})
        fake.fit.side_effect = None
        fake.fit.return_value = result
        with patch("statsmodels_negative_binomial.NegativeBinomial", return_value=fake):
            with self.assertRaisesRegex(ValueError, "non-finite parameters"):
                StatsmodelsNegativeBinomialNB2().fit(self.x, self.y)

    def test_registry_supplies_model_card_dependency_and_output_metadata(self):
        families = {
            "elastic_net": ("ElasticNet", "scikit-learn", "1.9.0"),
            "negative_binomial_regression": ("StatsmodelsNegativeBinomialNB2", "statsmodels", "0.14.6"),
            "extra_trees": ("ExtraTreesRegressor", "scikit-learn", "1.9.0"),
            "hist_gradient_boosting": ("HistGradientBoostingRegressor", "scikit-learn", "1.9.0"),
        }
        by_id = {candidate["model_id"]: candidate for candidate in self.registry["candidates"]}
        for model_id, expected in families.items():
            candidate = by_id[model_id]
            self.assertEqual((candidate["model_family"], candidate["estimator_library"], candidate["estimator_library_version"]), expected)
            self.assertTrue(candidate["output_domain_rule"])
            self.assertTrue(candidate["preprocessing_identity"])
            self.assertEqual(candidate["uncertainty_capability"], "model_specific_calibration_pending")
    def test_invalid_model_and_minimum_rows_fail(self):
        with self.assertRaises(ValueError):
            build_candidate_estimator("arbitrary", self.registry)
        with self.assertRaisesRegex(ValueError, "104"):
            StatsmodelsNegativeBinomialNB2().fit(self.x[:50], self.y[:50])


if __name__ == "__main__":
    unittest.main()
