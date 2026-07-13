"""Run-specific, non-causal diagnostics for the fitted validation estimator."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import sklearn
from jsonschema import Draft202012Validator, FormatChecker
from sklearn.inspection import permutation_importance

from formula_registry import known_formula_ids
from provenance import assert_same_provenance

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "config" / "model_explainability.schema.json"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "model_explainability.json"
SELECTED_SCHEMA_PATH = ROOT / "config" / "selected_model_explainability.schema.json"
SELECTED_OUTPUT_PATH = ROOT / "data" / "selected_model_explainability.json"
PERMUTATION_SCORING = "neg_mean_absolute_error"
PERMUTATION_REPEATS = 20
PERMUTATION_RANDOM_STATE = 42
PERMUTATION_MAX_SAMPLES = 1.0
RANK_DISAGREEMENT_THRESHOLD = 5


class ExplainabilityError(ValueError):
    """Raised when diagnostic generation or consistency validation fails."""


def _canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def feature_formula_id(feature_name: str) -> str:
    if feature_name.startswith(("rainfall_lag_", "temp_lag_", "humidity_lag_")):
        return "FEATURE.CLIMATE_LAGS"
    if feature_name.startswith("cases_lag_"):
        return "FEATURE.CASE_LAGS"
    if feature_name.startswith("cases_rolling_"):
        return "FEATURE.CASE_ROLLING"
    if feature_name.startswith("growth_rate_"):
        return "FEATURE.GROWTH_RATIOS"
    if feature_name in {"epi_week_sin", "epi_week_cos"}:
        return "FEATURE.SEASONAL_CYCLIC"
    if feature_name in {"monsoon_flag", "post_monsoon_flag"}:
        return "FEATURE.SEASON_FLAGS"
    raise ExplainabilityError(f"No governed formula mapping exists for feature {feature_name!r}.")


def feature_order_sha256(feature_names: Sequence[str]) -> str:
    return _canonical_json_sha256(list(feature_names))


def model_parameters_sha256(model_parameters: Mapping[str, Any]) -> str:
    return _canonical_json_sha256(dict(model_parameters))


def validation_matrix_sha256(
    validation_df: pd.DataFrame,
    feature_names: Sequence[str],
    target: str,
) -> str:
    columns = ["epi_year", "epi_week", *feature_names, target]
    missing = [column for column in columns if column not in validation_df.columns]
    if missing:
        raise ExplainabilityError(f"Validation matrix is missing columns: {missing}.")
    canonical = validation_df.loc[:, columns]
    if canonical.isna().any().any():
        raise ExplainabilityError("Validation matrix contains null values.")
    payload = canonical.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _period(first: pd.Series, last: pd.Series) -> dict[str, Any]:
    return {
        "start": {"epi_year": int(first["epi_year"]), "epi_week": int(first["epi_week"])},
        "end": {"epi_year": int(last["epi_year"]), "epi_week": int(last["epi_week"])},
    }


def _ranks(values: Sequence[float]) -> list[int]:
    order = sorted(range(len(values)), key=lambda index: (-float(values[index]), index))
    ranks = [0] * len(values)
    for rank, index in enumerate(order, start=1):
        ranks[index] = rank
    return ranks


def _schema_errors(value: Any, schema_path: str | Path = SCHEMA_PATH) -> list[str]:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [error.message for error in sorted(validator.iter_errors(value), key=lambda item: list(item.path))]


def validate_model_explainability(
    artifact: Mapping[str, Any],
    *,
    expected_provenance: Mapping[str, Any] | None = None,
    expected_feature_names: Sequence[str] | None = None,
    expected_validation_df: pd.DataFrame | None = None,
    expected_target: str | None = None,
    expected_model_card: Mapping[str, Any] | None = None,
    expected_artifact_sha256: str | None = None,
) -> None:
    errors = _schema_errors(dict(artifact))
    feature_names = list(artifact.get("feature_names", []))
    if expected_feature_names is not None and feature_names != list(expected_feature_names):
        errors.append("Explainability feature order does not match the canonical model feature order.")
    if artifact.get("feature_order_sha256") != feature_order_sha256(feature_names):
        errors.append("Explainability feature_order_sha256 is inconsistent.")
    if artifact.get("model_parameters_sha256") != model_parameters_sha256(artifact.get("model_parameters", {})):
        errors.append("Explainability model_parameters_sha256 is inconsistent.")
    if expected_target is not None and artifact.get("target") != expected_target:
        errors.append("Explainability target does not match validation target.")
    if expected_validation_df is not None:
        try:
            expected_digest = validation_matrix_sha256(
                expected_validation_df, feature_names, str(artifact.get("target"))
            )
            if artifact.get("validation_matrix_sha256") != expected_digest:
                errors.append("Explainability validation_matrix_sha256 is inconsistent.")
        except ExplainabilityError as exc:
            errors.append(str(exc))
    if expected_provenance is not None:
        try:
            assert_same_provenance(
                expected_provenance, artifact.get("provenance", {}),
                labels=("validation", "model_explainability.json"),
            )
        except Exception as exc:
            errors.append(str(exc))
    formula_ids = set(artifact.get("feature_formula_ids", []))
    unknown = sorted(formula_ids - known_formula_ids())
    if unknown:
        errors.append(f"Explainability references unknown formula IDs: {unknown}.")
    if expected_model_card is not None and artifact.get("active_model_evidence") is not False:
        comparisons = {
            "model_id": expected_model_card.get("model_id"),
            "model_version": expected_model_card.get("model_version"),
            "model_card_id": expected_model_card.get("model_card_id"),
            "model_card_version": expected_model_card.get("model_card_version"),
        }
        for key, expected in comparisons.items():
            if artifact.get(key) != expected:
                errors.append(f"Explainability {key} does not match the model card.")
        if expected_model_card.get("explainability_status") != "generated":
            errors.append("Model card does not mark explainability as generated.")
        if expected_artifact_sha256 is not None and expected_model_card.get("explainability_artifact_sha256") != expected_artifact_sha256:
            errors.append("Model card explainability artifact hash does not match exact artifact bytes.")
    if errors:
        raise ExplainabilityError(" ".join(dict.fromkeys(errors)))


def build_model_explainability(
    validation_model: Any,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_names: Sequence[str],
    target: str,
    model_parameters: Mapping[str, Any],
    provenance: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Build diagnostics from the already-fitted chronological validation model."""
    features = list(feature_names)
    if len(features) != 18 or len(set(features)) != 18:
        raise ExplainabilityError("Explainability requires exactly 18 unique canonical features.")
    if features != list(profile["selected_features"]):
        raise ExplainabilityError("Feature order differs from the deployment profile.")
    if train_df.empty or test_df.empty:
        raise ExplainabilityError("Explainability requires nonempty chronological train and holdout data.")
    mapped = [feature_formula_id(feature) for feature in features]
    x_test = test_df.loc[:, features].to_numpy()
    y_test = test_df.loc[:, target].to_numpy()
    native = np.asarray(validation_model.feature_importances_, dtype=float)
    if native.shape != (18,) or not np.isfinite(native).all() or (native < 0).any():
        raise ExplainabilityError("Native tree importance is invalid for the canonical 18-feature matrix.")
    native_sum = float(native.sum())
    if native_sum != 0.0 and not math.isclose(native_sum, 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ExplainabilityError("Native tree importance must sum to one or be all zero.")
    permutation = permutation_importance(
        validation_model, x_test, y_test,
        scoring=PERMUTATION_SCORING, n_repeats=PERMUTATION_REPEATS,
        random_state=PERMUTATION_RANDOM_STATE, n_jobs=1,
        max_samples=PERMUTATION_MAX_SAMPLES,
    )
    means = np.asarray(permutation.importances_mean, dtype=float)
    stds = np.asarray(permutation.importances_std, dtype=float)
    if means.shape != (18,) or stds.shape != (18,) or not np.isfinite(means).all() or not np.isfinite(stds).all():
        raise ExplainabilityError("Permutation importance returned invalid values.")
    impurity_ranks = _ranks(native)
    permutation_ranks = _ranks(means)
    ranking = []
    for index, feature in enumerate(features):
        mean = float(means[index])
        ranking.append({
            "feature_name": feature,
            "formula_id": mapped[index],
            "feature_index": index,
            "impurity_importance": float(native[index]),
            "permutation_mean": mean,
            "permutation_standard_deviation": float(stds[index]),
            "rank_by_impurity": impurity_ranks[index],
            "rank_by_permutation": permutation_ranks[index],
            "rank_disagreement": abs(permutation_ranks[index] - impurity_ranks[index]) >= RANK_DISAGREEMENT_THRESHOLD,
            "permutation_is_negative": mean < 0.0,
            "permutation_is_zero": mean == 0.0,
        })
    artifact = {
        "explainability_schema_version": "1.0",
        "explainability_version": "p0.4-v1",
        "availability_status": "generated",
        "model_id": "gradient_boosting",
        "model_version": "p0.4-v1",
        "estimator_family": "GradientBoostingRegressor",
        "estimator_library": profile["model"]["estimator_library"],
        "estimator_library_version": sklearn.__version__,
        "estimator_role": "chronological_holdout_validation_model",
        "model_parameters": dict(model_parameters),
        "model_parameters_sha256": model_parameters_sha256(model_parameters),
        "target": target,
        "forecast_horizon": {"value": 14, "unit": "days"},
        "feature_names": features,
        "feature_formula_ids": list(dict.fromkeys(mapped)),
        "feature_order_sha256": feature_order_sha256(features),
        "training_period": _period(train_df.iloc[0], train_df.iloc[-1]),
        "validation_period": _period(test_df.iloc[0], test_df.iloc[-1]),
        "validation_rows": len(test_df),
        "validation_matrix_sha256": validation_matrix_sha256(test_df, features, target),
        "evaluation_split": "final_chronological_20_percent",
        "importance_methods": ["holdout_permutation_importance", "native_tree_importance"],
        "impurity_importance": [float(value) for value in native],
        "permutation_importance": [float(value) for value in means],
        "permutation_std": [float(value) for value in stds],
        "permutation_repeats": PERMUTATION_REPEATS,
        "permutation_scoring": PERMUTATION_SCORING,
        "permutation_random_state": PERMUTATION_RANDOM_STATE,
        "permutation_max_samples": PERMUTATION_MAX_SAMPLES,
        "feature_ranking": ranking,
        "ranking_policy": {
            "primary": "permutation_mean_descending",
            "secondary": "impurity_importance_descending",
            "tie_breaker": "canonical_feature_index",
            "rank_disagreement_threshold": RANK_DISAGREEMENT_THRESHOLD,
        },
        "negative_importance_policy": "Negative values are preserved. Negative permutation importance may reflect noise, instability, correlated features, or sampling variation in this holdout.",
        "correlated_feature_warning": "Correlated case and climate lag features may divide, mask, or substitute for one another in both diagnostic methods.",
        "causal_interpretation_allowed": False,
        "stability_status": "not_evaluated_across_temporal_folds",
        "deployment_gate": profile["deployment_gate"],
        "data_mode": profile["data_mode"],
        "observed_data_mode": profile["observed_data_mode"],
        "limitations": [
            "Feature importance is a run-specific diagnostic of the fitted model. It does not establish causality, biological mechanism, clinical importance, or stability across seasons.",
            "These diagnostics describe the fitted chronological validation-model instance and do not directly explain the separately fitted all-data forecast-model instance.",
            "Importance is based on one chronological holdout; cross-fold, seasonal, and real-data stability have not been evaluated.",
            "Rankings may reflect relationships embedded in the synthetic benchmark data and may not transfer to real surveillance data.",
        ],
        "formula_registry_version": profile["formula_registry_version"],
        "formula_registry_sha256": profile["formula_registry_sha256"],
        "deployment_profile_id": profile["deployment_id"],
        "deployment_profile_sha256": provenance["deployment_profile_sha256"],
        "evidence_registry_sha256": provenance["evidence_registry_sha256"],
        "model_card_id": provenance["model_card_id"],
        "model_card_version": provenance["model_card_version"],
        "evidence_status": "historical",
        "compatibility_status": "compatibility_only",
        "active_model_evidence": False,
        "provenance": dict(provenance),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    validate_model_explainability(
        artifact, expected_provenance=provenance, expected_feature_names=features,
        expected_validation_df=test_df, expected_target=target,
    )
    return artifact


def validate_selected_model_explainability(
    artifact: Mapping[str, Any], *, expected_provenance: Mapping[str, Any] | None = None,
    expected_feature_names: Sequence[str] | None = None,
    expected_validation_df: pd.DataFrame | None = None,
    expected_comparison_sha256: str | None = None,
    expected_registry_sha256: str | None = None,
) -> None:
    errors = _schema_errors(dict(artifact), SELECTED_SCHEMA_PATH)
    features = list(artifact.get("feature_names", []))
    if expected_feature_names is not None and features != list(expected_feature_names):
        errors.append("Selected-model explainability feature order mismatch.")
    if artifact.get("feature_order_sha256") != feature_order_sha256(features):
        errors.append("Selected-model feature-order hash mismatch.")
    if artifact.get("adopted_model_parameters_sha256") != model_parameters_sha256(artifact.get("model_parameters", {})):
        errors.append("Selected-model parameter hash mismatch.")
    if expected_validation_df is not None:
        expected = validation_matrix_sha256(expected_validation_df, features, str(artifact.get("target")))
        if artifact.get("validation_matrix_sha256") != expected:
            errors.append("Selected-model validation-matrix hash mismatch.")
    if expected_comparison_sha256 is not None and artifact.get("comparison_artifact_sha256") != expected_comparison_sha256:
        errors.append("Selected-model comparison-artifact hash mismatch.")
    if expected_registry_sha256 is not None and artifact.get("candidate_registry_sha256") != expected_registry_sha256:
        errors.append("Selected-model candidate-registry hash mismatch.")
    if expected_provenance is not None:
        try:
            assert_same_provenance(expected_provenance, artifact.get("provenance", {}),
                                   labels=("selected validation", "selected_model_explainability.json"))
        except Exception as exc:
            errors.append(str(exc))
    native = np.asarray(artifact.get("native_importance", []), dtype=float)
    if native.shape != (18,) or not np.isfinite(native).all() or (native < 0).any():
        errors.append("Selected-model native importance is invalid.")
    elif native.sum() != 0 and not math.isclose(float(native.sum()), 1.0, rel_tol=1e-9, abs_tol=1e-9):
        errors.append("Selected-model native importance must sum to one or be all zero.")
    required_words = {
        "These diagnostics describe the selected Random Forest validation-model instance and do not directly explain the separately fitted all-data forecast instance.",
        "Feature importance is a model diagnostic and does not establish causality, biological mechanism, clinical importance, or stability across seasons.",
    }
    if not required_words.issubset(set(artifact.get("limitations", []))):
        errors.append("Selected-model explainability mandatory limitations are missing.")
    if errors:
        raise ExplainabilityError(" ".join(dict.fromkeys(errors)))


def build_selected_model_explainability(
    validation_model: Any, train_df: pd.DataFrame, test_df: pd.DataFrame,
    feature_names: Sequence[str], target: str, candidate: Mapping[str, Any],
    provenance: Mapping[str, Any], profile: Mapping[str, Any],
    candidate_registry_sha256: str, comparison_artifact_sha256: str,
) -> dict[str, Any]:
    """Build Random Forest diagnostics from the single governed 138/35 instance."""
    features = list(feature_names)
    if features != list(profile["selected_features"]) or len(features) != 18:
        raise ExplainabilityError("Selected-model diagnostics require the canonical 18-feature order.")
    if len(train_df) != 138 or len(test_df) != 35:
        raise ExplainabilityError("Selected-model diagnostics require the governed 138/35 split.")
    native = np.asarray(validation_model.feature_importances_, dtype=float)
    if native.shape != (18,) or not np.isfinite(native).all() or (native < 0).any():
        raise ExplainabilityError("Random Forest native importance is invalid.")
    if native.sum() != 0 and not math.isclose(float(native.sum()), 1.0, rel_tol=1e-9, abs_tol=1e-9):
        raise ExplainabilityError("Random Forest native importance must sum to one or be all zero.")
    x_test = test_df.loc[:, features].to_numpy()
    y_test = test_df.loc[:, target].to_numpy()
    permutation = permutation_importance(
        validation_model, x_test, y_test, scoring=PERMUTATION_SCORING,
        n_repeats=PERMUTATION_REPEATS, random_state=PERMUTATION_RANDOM_STATE,
        n_jobs=1, max_samples=PERMUTATION_MAX_SAMPLES,
    )
    means = np.asarray(permutation.importances_mean, dtype=float)
    stds = np.asarray(permutation.importances_std, dtype=float)
    if means.shape != (18,) or stds.shape != (18,) or not np.isfinite(means).all() or not np.isfinite(stds).all():
        raise ExplainabilityError("Random Forest permutation importance is invalid.")
    artifact = {
        "selected_model_explainability_schema_version": "1.0",
        "selected_model_explainability_version": "p1.2b-v1",
        "availability_status": "generated", "selected_model_id": "random_forest",
        "model_family": "RandomForestRegressor", "estimator_library": "scikit-learn",
        "estimator_library_version": sklearn.__version__,
        "model_parameters": dict(candidate["parameters"]),
        "adopted_model_parameters_sha256": candidate["parameters_sha256"],
        "estimator_role": "selected_model_chronological_holdout_validation_instance",
        "target": target, "forecast_horizon": {"value": 2, "unit": "weeks"},
        "feature_names": features,
        "feature_formula_ids": list(dict.fromkeys(feature_formula_id(feature) for feature in features)),
        "feature_order_sha256": feature_order_sha256(features),
        "training_period": _period(train_df.iloc[0], train_df.iloc[-1]),
        "validation_period": _period(test_df.iloc[0], test_df.iloc[-1]),
        "training_rows": len(train_df), "validation_rows": len(test_df),
        "validation_matrix_sha256": validation_matrix_sha256(test_df, features, target),
        "evaluation_split": "legacy_final_chronological_20_percent",
        "importance_methods": ["native_random_forest_impurity_importance", "holdout_permutation_importance"],
        "native_importance": [float(value) for value in native],
        "permutation_importance": [float(value) for value in means],
        "permutation_std": [float(value) for value in stds],
        "permutation_settings": {"scoring": PERMUTATION_SCORING, "n_repeats": 20,
                                 "random_state": 42, "n_jobs": 1, "max_samples": 1.0},
        "feature_ranking": [{"feature_name": feature, "feature_index": index,
                             "native_importance": float(native[index]),
                             "permutation_mean": float(means[index]),
                             "permutation_standard_deviation": float(stds[index]),
                             "permutation_is_negative": bool(means[index] < 0)}
                            for index, feature in enumerate(features)],
        "negative_importance_policy": "Negative permutation values are preserved.",
        "causal_interpretation_allowed": False,
        "rolling_importance_stability_status": "not_evaluated_across_temporal_folds",
        "limitations": [
            "These diagnostics describe the selected Random Forest validation-model instance and do not directly explain the separately fitted all-data forecast instance.",
            "Feature importance is a model diagnostic and does not establish causality, biological mechanism, clinical importance, or stability across seasons.",
            "Diagnostics use deterministic synthetic data and one legacy chronological holdout.",
        ],
        "deployment_id": profile["deployment_id"], "deployment_gate": profile["deployment_gate"],
        "data_mode": profile["data_mode"], "candidate_registry_sha256": candidate_registry_sha256,
        "comparison_artifact_sha256": comparison_artifact_sha256,
        "adoption_status": "adopted_p1.2b", "adoption_policy_version": "p1.2b-v1",
        "formula_registry_version": profile["formula_registry_version"],
        "formula_registry_sha256": profile["formula_registry_sha256"],
        "deployment_profile_sha256": provenance["deployment_profile_sha256"],
        "evidence_registry_sha256": provenance["evidence_registry_sha256"],
        "provenance": dict(provenance),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    validate_selected_model_explainability(
        artifact, expected_provenance=provenance, expected_feature_names=features,
        expected_validation_df=test_df, expected_comparison_sha256=comparison_artifact_sha256,
        expected_registry_sha256=candidate_registry_sha256,
    )
    return artifact


def write_explainability_atomic(
    artifact: Mapping[str, Any], path: str | Path = DEFAULT_OUTPUT_PATH
) -> Path:
    """Validate in memory, then atomically publish complete JSON bytes."""
    validate_model_explainability(artifact)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(artifact, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        return path
    except Exception:
        if temporary is not None and temporary.exists():
            temporary.unlink()
        raise
