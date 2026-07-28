"""Trusted fold-local spline Poisson adapter for the governed 18-feature contract."""
from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import PoissonRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import SplineTransformer, StandardScaler

from feature_engineering import FEATURE_COLUMNS


NONLINEAR_COLUMNS = (
    "rainfall_lag_2w",
    "rainfall_lag_4w",
    "temp_lag_2w",
    "temp_lag_4w",
    "humidity_lag_2w",
    "humidity_lag_4w",
)
LINEAR_COLUMNS = (
    "cases_lag_1w",
    "cases_lag_2w",
    "cases_lag_4w",
    "epi_week_sin",
    "epi_week_cos",
)
EXCLUDED_COLUMNS = tuple(
    column
    for column in FEATURE_COLUMNS
    if column not in NONLINEAR_COLUMNS and column not in LINEAR_COLUMNS
)
TRANSFORMED_COLUMN_ORDER = "spline_basis_then_scaled_linear"
FEATURE_ORDER_SHA256 = "aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85"
GOVERNED_PARAMETERS = {
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
GOVERNED_PREPROCESSING = {
    "type": "SplineColumnTransformer",
    "fit_scope": "fold_training_rows_only",
    "input_feature_order_sha256": FEATURE_ORDER_SHA256,
    "nonlinear_columns": list(NONLINEAR_COLUMNS),
    "linear_columns": list(LINEAR_COLUMNS),
    "spline_degree": 2,
    "spline_n_knots": 4,
    "spline_knots": "quantile",
    "spline_extrapolation": "constant",
    "spline_include_bias": False,
    "linear_scaling": "StandardScaler",
    "remainder": "drop",
    "transformed_column_order": TRANSFORMED_COLUMN_ORDER,
}


class SklearnPoissonGAM:
    """A fail-closed sklearn-compatible point estimator with fold-local basis fitting."""

    def __init__(
        self,
        *,
        alpha: float,
        fit_intercept: bool,
        max_iter: int,
        tol: float,
        spline_degree: int,
        spline_n_knots: int,
        spline_knots: str,
        spline_extrapolation: str,
        spline_include_bias: bool,
        linear_scaling: str,
        remainder: str,
    ) -> None:
        parameters = {
            "alpha": alpha,
            "fit_intercept": fit_intercept,
            "max_iter": max_iter,
            "tol": tol,
            "spline_degree": spline_degree,
            "spline_n_knots": spline_n_knots,
            "spline_knots": spline_knots,
            "spline_extrapolation": spline_extrapolation,
            "spline_include_bias": spline_include_bias,
            "linear_scaling": linear_scaling,
            "remainder": remainder,
        }
        self._validate_parameters(parameters)
        for name, value in parameters.items():
            setattr(self, name, value)

    @staticmethod
    def _validate_parameters(parameters: dict[str, Any]) -> None:
        if (
            not isinstance(parameters["alpha"], (int, float))
            or isinstance(parameters["alpha"], bool)
            or not math.isfinite(float(parameters["alpha"]))
            or float(parameters["alpha"]) < 0
        ):
            raise ValueError("Poisson GAM alpha must be finite and non-negative.")
        if not isinstance(parameters["fit_intercept"], bool):
            raise ValueError("Poisson GAM fit_intercept must be boolean.")
        if (
            not isinstance(parameters["max_iter"], int)
            or isinstance(parameters["max_iter"], bool)
            or parameters["max_iter"] < 1
        ):
            raise ValueError("Poisson GAM max_iter must be a positive integer.")
        if (
            not isinstance(parameters["tol"], (int, float))
            or isinstance(parameters["tol"], bool)
            or not math.isfinite(float(parameters["tol"]))
            or float(parameters["tol"]) <= 0
        ):
            raise ValueError("Poisson GAM tolerance must be finite and positive.")
        if (
            not isinstance(parameters["spline_degree"], int)
            or isinstance(parameters["spline_degree"], bool)
            or not 1 <= parameters["spline_degree"] <= 3
        ):
            raise ValueError("Poisson GAM spline degree must be between one and three.")
        if (
            not isinstance(parameters["spline_n_knots"], int)
            or isinstance(parameters["spline_n_knots"], bool)
            or not 3 <= parameters["spline_n_knots"] <= 10
        ):
            raise ValueError("Poisson GAM knot count must be between three and ten.")
        if parameters["spline_knots"] not in {"quantile", "uniform"}:
            raise ValueError("Poisson GAM knot strategy is unsupported.")
        if parameters["spline_extrapolation"] not in {"constant", "linear", "error"}:
            raise ValueError("Poisson GAM extrapolation policy is unsupported.")
        if not isinstance(parameters["spline_include_bias"], bool):
            raise ValueError("Poisson GAM include_bias must be boolean.")
        if parameters["linear_scaling"] != "StandardScaler":
            raise ValueError("Poisson GAM linear scaling contract is unsupported.")
        if parameters["remainder"] != "drop":
            raise ValueError("Poisson GAM remainder contract is unsupported.")

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        del deep
        return {
            name: getattr(self, name)
            for name in (
                "alpha",
                "fit_intercept",
                "max_iter",
                "tol",
                "spline_degree",
                "spline_n_knots",
                "spline_knots",
                "spline_extrapolation",
                "spline_include_bias",
                "linear_scaling",
                "remainder",
            )
        }

    def _matrix(self, value: Any) -> np.ndarray:
        if isinstance(value, pd.DataFrame):
            if list(value.columns) != list(FEATURE_COLUMNS):
                raise ValueError("Poisson GAM feature columns or order are invalid.")
            matrix = value.to_numpy(dtype=float)
        else:
            matrix = np.asarray(value, dtype=float)
        if matrix.ndim != 2 or matrix.shape[1] != len(FEATURE_COLUMNS):
            raise ValueError("Poisson GAM input dimensions are invalid.")
        if not np.isfinite(matrix).all():
            raise ValueError("Poisson GAM input contains non-finite values.")
        return matrix

    @staticmethod
    def _finite_transformed(value: Any) -> np.ndarray:
        matrix = value.toarray() if hasattr(value, "toarray") else np.asarray(value)
        matrix = np.asarray(matrix, dtype=float)
        if matrix.ndim != 2 or not np.isfinite(matrix).all():
            raise ValueError("Poisson GAM transformed design is invalid.")
        return matrix

    def _new_pipeline(self) -> Pipeline:
        nonlinear_indexes = [FEATURE_COLUMNS.index(column) for column in NONLINEAR_COLUMNS]
        linear_indexes = [FEATURE_COLUMNS.index(column) for column in LINEAR_COLUMNS]
        preprocessing = ColumnTransformer(
            [
                (
                    "spline",
                    SplineTransformer(
                        degree=self.spline_degree,
                        n_knots=self.spline_n_knots,
                        knots=self.spline_knots,
                        extrapolation=self.spline_extrapolation,
                        include_bias=self.spline_include_bias,
                    ),
                    nonlinear_indexes,
                ),
                ("linear", StandardScaler(), linear_indexes),
            ],
            remainder=self.remainder,
            verbose_feature_names_out=True,
        )
        model = PoissonRegressor(
            alpha=float(self.alpha),
            fit_intercept=self.fit_intercept,
            max_iter=self.max_iter,
            tol=float(self.tol),
        )
        return Pipeline([("preprocessing", preprocessing), ("model", model)])

    def fit(self, X: Any, y: Any) -> "SklearnPoissonGAM":
        matrix = self._matrix(X)
        target = np.asarray(y, dtype=float)
        if (
            target.ndim != 1
            or target.shape[0] != matrix.shape[0]
            or not np.isfinite(target).all()
            or (target < 0).any()
        ):
            raise ValueError("Poisson GAM target is invalid.")
        pipeline = self._new_pipeline()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            pipeline.fit(matrix, target)
            transformed = pipeline.named_steps["preprocessing"].transform(matrix)
        if caught:
            categories = ",".join(sorted({item.category.__name__ for item in caught}))
            raise ValueError(f"Poisson GAM fit emitted an unapproved warning: {categories}.")
        transformed_matrix = self._finite_transformed(transformed)
        model = pipeline.named_steps["model"]
        coefficients = np.asarray(model.coef_, dtype=float)
        if (
            coefficients.ndim != 1
            or coefficients.shape[0] != transformed_matrix.shape[1]
            or not np.isfinite(coefficients).all()
            or not math.isfinite(float(model.intercept_))
        ):
            raise ValueError("Poisson GAM fitted coefficients are invalid.")
        self.pipeline_ = pipeline
        self.transformed_feature_count_ = int(transformed_matrix.shape[1])
        self.n_features_in_ = int(matrix.shape[1])
        return self

    def predict(self, X: Any) -> np.ndarray:
        if not hasattr(self, "pipeline_"):
            raise ValueError("Poisson GAM is not fitted.")
        matrix = self._matrix(X)
        fitted_model = self.pipeline_.named_steps["model"]
        if (
            not np.isfinite(np.asarray(fitted_model.coef_, dtype=float)).all()
            or not math.isfinite(float(fitted_model.intercept_))
        ):
            raise ValueError("Poisson GAM fitted coefficients are invalid.")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            transformed = self.pipeline_.named_steps["preprocessing"].transform(matrix)
            transformed_matrix = self._finite_transformed(transformed)
            prediction = np.asarray(
                self.pipeline_.named_steps["model"].predict(transformed_matrix),
                dtype=float,
            )
        if caught:
            categories = ",".join(sorted({item.category.__name__ for item in caught}))
            raise ValueError(f"Poisson GAM prediction emitted an unapproved warning: {categories}.")
        if transformed_matrix.shape[1] != self.transformed_feature_count_:
            raise ValueError("Poisson GAM transformed dimensions changed after fit.")
        if (
            prediction.ndim != 1
            or prediction.shape[0] != matrix.shape[0]
            or not np.isfinite(prediction).all()
            or (prediction < 0).any()
        ):
            raise ValueError("Poisson GAM prediction is invalid.")
        return prediction

    def transformed_feature_names(self) -> tuple[str, ...]:
        if not hasattr(self, "pipeline_"):
            raise ValueError("Poisson GAM is not fitted.")
        names = self.pipeline_.named_steps["preprocessing"].get_feature_names_out()
        return tuple(str(value) for value in names)
