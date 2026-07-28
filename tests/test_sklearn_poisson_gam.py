from __future__ import annotations

import sys
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import PoissonRegressor


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from feature_engineering import FEATURE_COLUMNS, build_features
from sklearn_poisson_gam import (
    EXCLUDED_COLUMNS,
    LINEAR_COLUMNS,
    NONLINEAR_COLUMNS,
    SklearnPoissonGAM,
)


PARAMETERS = {
    "alpha": 1.0,
    "fit_intercept": True,
    "max_iter": 1000,
    "tol": 0.0001,
    "spline_degree": 2,
    "spline_n_knots": 4,
    "spline_knots": "quantile",
    "spline_extrapolation": "constant",
    "spline_include_bias": False,
    "linear_scaling": "StandardScaler",
    "remainder": "drop",
}


class SklearnPoissonGAMTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frame, _ = build_features(output_path=None)
        cls.X = frame[FEATURE_COLUMNS].to_numpy(float)
        cls.y = frame["target_cases_next_2w"].to_numpy(float)

    def test_governed_projection_is_small_and_complete(self):
        self.assertEqual(len(NONLINEAR_COLUMNS), 6)
        self.assertEqual(len(LINEAR_COLUMNS), 5)
        self.assertEqual(len(EXCLUDED_COLUMNS), 7)
        self.assertEqual(
            set(NONLINEAR_COLUMNS) | set(LINEAR_COLUMNS) | set(EXCLUDED_COLUMNS),
            set(FEATURE_COLUMNS),
        )

    def test_construction_fit_prediction_and_transformed_order_are_deterministic(self):
        first = SklearnPoissonGAM(**PARAMETERS).fit(self.X[:104], self.y[:104])
        second = SklearnPoissonGAM(**PARAMETERS).fit(self.X[:104], self.y[:104])
        self.assertEqual(first.transformed_feature_count_, 29)
        self.assertEqual(first.transformed_feature_names(), second.transformed_feature_names())
        self.assertTrue(
            all(name.startswith("spline__") for name in first.transformed_feature_names()[:24])
        )
        self.assertTrue(
            all(name.startswith("linear__") for name in first.transformed_feature_names()[24:])
        )
        prediction = first.predict(self.X[105:110])
        self.assertTrue(np.isfinite(prediction).all())
        self.assertTrue((prediction >= 0).all())
        np.testing.assert_array_equal(prediction, second.predict(self.X[105:110]))

    def test_knots_and_scaler_are_fitted_only_from_training_rows(self):
        model = SklearnPoissonGAM(**PARAMETERS).fit(self.X[:104], self.y[:104])
        preprocessing = model.pipeline_.named_steps["preprocessing"]
        spline = preprocessing.named_transformers_["spline"]
        scaler = preprocessing.named_transformers_["linear"]
        linear_indexes = [FEATURE_COLUMNS.index(column) for column in LINEAR_COLUMNS]
        np.testing.assert_allclose(scaler.mean_, self.X[:104, linear_indexes].mean(axis=0))

        changed_validation = self.X[105:110].copy()
        changed_validation[:, 0] = 10**9
        before = tuple(np.asarray(value.t).copy() for value in spline.bsplines_)
        model.predict(changed_validation)
        after = tuple(np.asarray(value.t).copy() for value in spline.bsplines_)
        for left, right in zip(before, after):
            np.testing.assert_array_equal(left, right)
        np.testing.assert_allclose(scaler.mean_, self.X[:104, linear_indexes].mean(axis=0))

    def test_constant_extrapolation_remains_finite(self):
        model = SklearnPoissonGAM(**PARAMETERS).fit(self.X[:104], self.y[:104])
        extreme = self.X[[105]].copy()
        extreme[:, :6] = 10**9
        prediction = model.predict(extreme)
        self.assertTrue(np.isfinite(prediction).all())
        self.assertGreaterEqual(prediction[0], 0)

    def test_invalid_parameters_inputs_and_targets_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "knot strategy"):
            SklearnPoissonGAM(**{**PARAMETERS, "spline_knots": "adaptive"})
        model = SklearnPoissonGAM(**PARAMETERS)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            model.fit(self.X[:104, :-1], self.y[:104])
        invalid = self.X[:104].copy()
        invalid[0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "non-finite"):
            model.fit(invalid, self.y[:104])
        target = self.y[:104].copy()
        target[0] = -1
        with self.assertRaisesRegex(ValueError, "target"):
            model.fit(self.X[:104], target)

    def test_unapproved_warning_fails_closed(self):
        original = PoissonRegressor.fit

        def warning_fit(estimator, X, y, *args, **kwargs):
            warnings.warn("forced", ConvergenceWarning)
            return original(estimator, X, y, *args, **kwargs)

        with patch.object(PoissonRegressor, "fit", warning_fit):
            with self.assertRaisesRegex(ValueError, "unapproved warning"):
                SklearnPoissonGAM(**PARAMETERS).fit(self.X[:104], self.y[:104])

    def test_nonfinite_coefficients_and_predictions_fail_closed(self):
        model = SklearnPoissonGAM(**PARAMETERS).fit(self.X[:104], self.y[:104])
        model.pipeline_.named_steps["model"].coef_[0] = np.nan
        with self.assertRaisesRegex(ValueError, "coefficients"):
            model.predict(self.X[[105]])


if __name__ == "__main__":
    unittest.main()
