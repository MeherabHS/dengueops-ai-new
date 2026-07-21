"""Governed statsmodels Negative Binomial NB2 adapter."""
from __future__ import annotations

import warnings

import numpy as np
from sklearn.preprocessing import StandardScaler
from statsmodels.discrete.discrete_model import NegativeBinomial
from statsmodels.tools import add_constant


class StatsmodelsNegativeBinomialNB2:
    """Small fit/predict adapter with training-local scaling and NB2 dispersion."""

    minimum_training_rows = 104

    def __init__(
        self,
        *,
        loglike_method: str = "nb2",
        fit_intercept: bool = True,
        optimizer: str = "bfgs",
        max_iter: int = 200,
        gtol: float = 1e-6,
        full_output: bool = True,
        disp: bool = False,
        check_rank: bool = True,
        missing: str = "raise",
        dispersion: str = "estimated_per_training_fit",
    ) -> None:
        expected = (loglike_method, fit_intercept, optimizer, full_output, disp, check_rank, missing, dispersion)
        if expected != ("nb2", True, "bfgs", True, False, True, "raise", "estimated_per_training_fit"):
            raise ValueError("Unsupported governed Negative Binomial configuration.")
        if max_iter != 200 or gtol != 1e-6:
            raise ValueError("Unsupported governed Negative Binomial optimizer configuration.")
        self.max_iter = max_iter
        self.gtol = gtol

    @staticmethod
    def _arrays(x, y=None):
        features = np.asarray(x, dtype=float)
        if features.ndim != 2 or not np.isfinite(features).all():
            raise ValueError("Negative Binomial features must be a finite two-dimensional array.")
        if y is None:
            return features
        target = np.asarray(y, dtype=float)
        if target.ndim != 1 or len(target) != len(features) or not np.isfinite(target).all() or (target < 0).any():
            raise ValueError("Negative Binomial targets must be finite nonnegative counts.")
        return features, target

    def fit(self, x, y):
        features, target = self._arrays(x, y)
        if len(features) < self.minimum_training_rows:
            raise ValueError(f"Negative Binomial requires at least {self.minimum_training_rows} training rows.")
        self.scaler_ = StandardScaler()
        design = add_constant(self.scaler_.fit_transform(features), has_constant="add")
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                model = NegativeBinomial(target, design, loglike_method="nb2", check_rank=True, missing="raise")
                result = model.fit(method="bfgs", maxiter=self.max_iter, gtol=self.gtol, full_output=True, disp=False)
        except Exception as exc:
            raise ValueError("Negative Binomial fit failed.") from exc
        if caught:
            raise ValueError("Negative Binomial fit emitted a disqualifying warning.")
        converged = bool(getattr(result, "mle_retvals", {}).get("converged", False))
        if not converged:
            raise ValueError("Negative Binomial fit did not converge.")
        parameters = np.asarray(result.params, dtype=float)
        if not np.isfinite(parameters).all():
            raise ValueError("Negative Binomial fit produced non-finite parameters.")
        dispersion = float(parameters[-1])
        if not np.isfinite(dispersion) or dispersion <= 0:
            raise ValueError("Negative Binomial fit produced invalid dispersion.")
        self.result_ = result
        self.fit_evidence_ = {
            "distribution": "NB2",
            "converged": True,
            "optimizer": "bfgs",
            "dispersion": dispersion,
            "dispersionScope": "training_fit_only",
        }
        return self

    def predict(self, x) -> np.ndarray:
        if not hasattr(self, "result_"):
            raise ValueError("Negative Binomial adapter is not fitted.")
        features = self._arrays(x)
        design = add_constant(self.scaler_.transform(features), has_constant="add")
        predictions = np.asarray(self.result_.predict(design), dtype=float)
        if predictions.shape != (len(features),):
            raise ValueError("Negative Binomial prediction dimensions are invalid.")
        if not np.isfinite(predictions).all():
            raise ValueError("Negative Binomial predictions must be finite.")
        if (predictions < 0).any():
            raise ValueError("Negative Binomial predictions must not be negative.")
        return predictions
