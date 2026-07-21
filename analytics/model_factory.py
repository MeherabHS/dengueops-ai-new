"""Authoritative construction and validation for governed learned models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingRegressor,
                              HistGradientBoostingRegressor, RandomForestRegressor)
from sklearn.linear_model import ElasticNet, PoissonRegressor, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from feature_engineering import FEATURE_COLUMNS
from statsmodels_negative_binomial import StatsmodelsNegativeBinomialNB2

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = ROOT / "config" / "candidate_models.json"
HISTORICAL_REGISTRY_PATH = ROOT / "config" / "candidate_models_p1.2a-v1.json"
HISTORICAL_REGISTRY_SHA256 = "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4"
REGISTRY_SCHEMA_PATH = ROOT / "config" / "candidate_models.schema.json"
FORBIDDEN_TUNING_FIELDS = {
    "parameter_grid", "search_space", "cross_validation_selector", "trial_count",
    "optimization_objective", "tuning_method",
}
LEARNED_MODEL_IDS = {
    "gradient_boosting", "random_forest", "ridge_regression", "poisson_regression",
    "elastic_net", "negative_binomial_regression", "extra_trees", "hist_gradient_boosting",
}
BASELINE_MODEL_IDS = {"moving_average_4w", "seasonal_naive_52w"}
GOVERNED_PARAMETER_HASHES = {
    "moving_average_4w": "c1eff3c6bc5cf02b7176abcbf33348f0d3962791d002686d53e6654cae04a18c",
    "seasonal_naive_52w": "2395c31b374ed6b361163411122c1c0c62d2db1e16496010f3919cdd5928e80b",
    "ridge_regression": "f59e0d298750b54d9ab8312c6a68a4eaf4910bea81042dd3a1c4711dcb307e5b",
    "poisson_regression": "f1d10b8e22303b8d4f550861b54971e5ef2beba310a11b6458544be97871098b",
    "random_forest": "ac37d2d2947de2f6004d39ecdfa3290c5d65901b796f1eb1fd248ad658e1b1e0",
    "gradient_boosting": "4741d1f17b3bf98988b886dcb6157a9382b569e3264e1004d2f3eb474bd34963",
    "elastic_net": "780e70db5088d04dfb4ac303fe4ef63db07ce115060e3c70129ec9df28f36542",
    "negative_binomial_regression": "b559617142d071297a6563a0834dddc6ab1f11f06d9168d33e14f3b2d051d8b7",
    "extra_trees": "aa7cd8f0395c6e2dfead3b831e2ed5b3dcf939335e0b668c07746d2952243956",
    "hist_gradient_boosting": "de877edd7bb851b44e93fde49d06e1b913b43440114d0708577c2df72b855362",
}
GOVERNED_ESTIMATOR_IDENTITIES = {
    "moving_average_4w": ("MovingAverage4W", "dengueops", "checkpoint-dd2fc901c1c0467481c4dfa8e284f6ef2d8e3979"),
    "seasonal_naive_52w": ("SeasonalNaive52W", "dengueops", "checkpoint-dd2fc901c1c0467481c4dfa8e284f6ef2d8e3979"),
    "ridge_regression": ("Ridge", "scikit-learn", "1.9.0"),
    "poisson_regression": ("PoissonRegressor", "scikit-learn", "1.9.0"),
    "random_forest": ("RandomForestRegressor", "scikit-learn", "1.9.0"),
    "gradient_boosting": ("GradientBoostingRegressor", "scikit-learn", "1.9.0"),
    "elastic_net": ("ElasticNet", "scikit-learn", "1.9.0"),
    "negative_binomial_regression": ("StatsmodelsNegativeBinomialNB2", "statsmodels", "0.14.6"),
    "extra_trees": ("ExtraTreesRegressor", "scikit-learn", "1.9.0"),
    "hist_gradient_boosting": ("HistGradientBoostingRegressor", "scikit-learn", "1.9.0"),
}


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_forbidden_tuning_fields(value: Any, found: list[str]) -> None:
    if isinstance(value, dict):
        found.extend(key for key in value if key in FORBIDDEN_TUNING_FIELDS)
        for child in value.values():
            _find_forbidden_tuning_fields(child, found)
    elif isinstance(value, list):
        for child in value:
            _find_forbidden_tuning_fields(child, found)


def validate_candidate_configuration(candidate: dict, registry: dict | None = None) -> dict:
    """Validate one frozen learned-model configuration without constructing it."""
    errors: list[str] = []
    model_id = candidate.get("model_id")
    if model_id not in LEARNED_MODEL_IDS:
        errors.append(f"Unsupported learned candidate: {model_id}.")
    historical = candidate.get("enabled") is True and "candidate_class" not in candidate
    if not historical:
        if candidate.get("candidate_class") != "learned_model" or candidate.get("selection_role") != "learned_selectable":
            errors.append(f"Candidate {model_id} is not a selectable learned model.")
        if candidate.get("selectable") is not True:
            errors.append(f"Candidate {model_id} is not selectable.")
    if candidate.get("parameters_sha256") != canonical_sha256(candidate.get("parameters", {})):
        errors.append(f"Parameter hash mismatch for {model_id}.")
    preprocessing = candidate.get("preprocessing", {})
    expected_preprocessing = {
        "gradient_boosting": "none", "random_forest": "none",
        "ridge_regression": "StandardScaler", "poisson_regression": "StandardScaler",
        "elastic_net": "StandardScaler", "negative_binomial_regression": "StandardScaler",
        "extra_trees": "none", "hist_gradient_boosting": "none",
    }.get(model_id)
    if preprocessing.get("type") != expected_preprocessing:
        errors.append(f"Invalid preprocessing policy for {model_id}.")
    if not historical and candidate.get("preprocessing_identity") != canonical_sha256(preprocessing):
        errors.append(f"Preprocessing identity mismatch for {model_id}.")
    if expected_preprocessing == "StandardScaler" and preprocessing.get("fit_scope") != "fold_training_rows_only":
        errors.append(f"Scaler for {model_id} must be fitted on training rows only.")
    forbidden: list[str] = []
    _find_forbidden_tuning_fields(candidate, forbidden)
    if forbidden:
        errors.append(f"Tuning fields are prohibited: {', '.join(sorted(set(forbidden)))}.")
    if registry is not None:
        if registry.get("output_domain_policy") != "preserve_raw_and_publish_maximum_of_zero_and_raw_prediction":
            errors.append("Unsupported output-domain policy.")
        if registry.get("feature_order_sha256") != canonical_sha256(list(FEATURE_COLUMNS)):
            errors.append("Candidate registry feature order mismatch.")
        if registry.get("target") != "target_cases_next_2w" or registry.get("horizon_weeks") != 2:
            errors.append("Candidate registry target or horizon mismatch.")
        if not historical and candidate.get("feature_order_sha256") != registry.get("feature_order_sha256"):
            errors.append(f"Candidate feature order mismatch for {model_id}.")
        if not historical and (candidate.get("target") != registry.get("target") or candidate.get("horizon_weeks") != registry.get("horizon_weeks")):
            errors.append(f"Candidate target or horizon mismatch for {model_id}.")
    if errors:
        raise ValueError(" ".join(dict.fromkeys(errors)))
    return candidate


def load_and_validate_candidate_registry(path: Path = DEFAULT_REGISTRY_PATH) -> tuple[dict, str]:
    """Load exact registry bytes, apply schema and semantic validation, return hash."""
    if Path(path).resolve() == HISTORICAL_REGISTRY_PATH.resolve():
        return load_historical_candidate_registry()
    payload = path.read_bytes()
    try:
        registry = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Candidate registry bytes are not valid UTF-8 JSON.") from exc
    schema = json.loads(REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(registry)]
    ids = [candidate.get("model_id") for candidate in registry.get("candidates", [])]
    if len(ids) != len(set(ids)):
        errors.append("Candidate model IDs must be unique.")
    if set(ids) != LEARNED_MODEL_IDS | BASELINE_MODEL_IDS:
        errors.append("Candidate registry must contain exactly eight learned candidates and two baselines.")
    parameter_hashes = [candidate.get("parameters_sha256") for candidate in registry.get("candidates", [])]
    if len(parameter_hashes) != len(set(parameter_hashes)):
        errors.append("Candidate parameter identities must be unique.")
    for candidate in registry.get("candidates", []):
        if candidate.get("parameters_sha256") != GOVERNED_PARAMETER_HASHES.get(candidate.get("model_id")):
            errors.append(f"Frozen parameter identity mismatch for {candidate.get('model_id')}.")
        identity = (
            candidate.get("model_family"),
            candidate.get("estimator_library"),
            candidate.get("estimator_library_version"),
        )
        if identity != GOVERNED_ESTIMATOR_IDENTITIES.get(candidate.get("model_id")):
            errors.append(f"Frozen estimator identity mismatch for {candidate.get('model_id')}.")
    forbidden: list[str] = []
    _find_forbidden_tuning_fields(registry, forbidden)
    if forbidden:
        errors.append(f"Tuning fields are prohibited: {', '.join(sorted(set(forbidden)))}.")
    if registry.get("feature_order_sha256") != canonical_sha256(list(FEATURE_COLUMNS)):
        errors.append("Candidate registry feature order mismatch.")
    if errors:
        raise ValueError(" ".join(dict.fromkeys(errors)))
    for candidate in registry["candidates"]:
        if candidate["model_id"] in LEARNED_MODEL_IDS:
            validate_candidate_configuration(candidate, registry)
        else:
            model_id = candidate.get("model_id")
            if candidate.get("candidate_class") != "comparison_baseline" or candidate.get("selection_role") != "baseline_only" or candidate.get("selectable") is not False:
                raise ValueError(f"Baseline {model_id} must be comparison-only and non-selectable.")
            if candidate.get("parameters_sha256") != canonical_sha256(candidate.get("parameters", {})):
                raise ValueError(f"Parameter hash mismatch for {model_id}.")
            if candidate.get("preprocessing_identity") != canonical_sha256(candidate.get("preprocessing", {})):
                raise ValueError(f"Preprocessing identity mismatch for {model_id}.")
            if candidate.get("feature_order_sha256") != registry.get("feature_order_sha256"):
                raise ValueError(f"Candidate feature order mismatch for {model_id}.")
    return registry, hashlib.sha256(payload).hexdigest()


def load_historical_candidate_registry() -> tuple[dict, str]:
    """Load the immutable Phase 1 registry without applying v2 reinterpretation."""
    payload = HISTORICAL_REGISTRY_PATH.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    registry = json.loads(payload.decode("utf-8"))
    if digest != HISTORICAL_REGISTRY_SHA256 or registry.get("candidate_registry_version") != "p1.2a-v1":
        raise ValueError("Historical candidate registry identity mismatch.")
    ids = [candidate.get("model_id") for candidate in registry.get("candidates", [])]
    if len(ids) != 7 or len(set(ids)) != 7:
        raise ValueError("Historical candidate registry population mismatch.")
    for candidate in registry["candidates"]:
        if candidate.get("parameters_sha256") != canonical_sha256(candidate.get("parameters", {})):
            raise ValueError("Historical candidate parameter identity mismatch.")
    if registry.get("feature_order_sha256") != canonical_sha256(list(FEATURE_COLUMNS)):
        raise ValueError("Historical candidate feature order mismatch.")
    return registry, digest


def candidate_configuration(model_id: str, candidate_registry: dict) -> dict:
    candidate = next(
        (item for item in candidate_registry.get("candidates", []) if item.get("model_id") == model_id),
        None,
    )
    if candidate is None:
        raise ValueError(f"Candidate {model_id} is not present in the governed registry.")
    return validate_candidate_configuration(candidate, candidate_registry)


def build_candidate_estimator(model_id: str, candidate_registry: dict):
    """Construct a fresh estimator using only the candidate registry parameters."""
    candidate = candidate_configuration(model_id, candidate_registry)
    parameters = dict(candidate["parameters"])
    if model_id == "gradient_boosting":
        return GradientBoostingRegressor(**parameters)
    if model_id == "random_forest":
        return RandomForestRegressor(**parameters)
    if model_id == "ridge_regression":
        return Pipeline([("scaler", StandardScaler()), ("model", Ridge(**parameters))])
    if model_id == "poisson_regression":
        return Pipeline([("scaler", StandardScaler()), ("model", PoissonRegressor(**parameters))])
    if model_id == "elastic_net":
        return Pipeline([("scaler", StandardScaler()), ("model", ElasticNet(**parameters))])
    if model_id == "negative_binomial_regression":
        return StatsmodelsNegativeBinomialNB2(**parameters)
    if model_id == "extra_trees":
        return ExtraTreesRegressor(**parameters)
    if model_id == "hist_gradient_boosting":
        return HistGradientBoostingRegressor(**parameters)
    raise ValueError(f"Unsupported learned candidate: {model_id}.")


def build_active_forecast_estimator(profile: dict, comparison_artifact: dict, candidate_registry: dict):
    """Construct the profile-targeted winner; this API deliberately has no fallback."""
    target = profile.get("candidate_comparison", {}).get("adoption_target_model")
    selected = comparison_artifact.get("comparison_selected_model")
    if not target or selected != target:
        raise ValueError("Comparison winner differs from the deployment-profile adoption target.")
    if profile.get("model", {}).get("model_id") != selected:
        raise ValueError("Deployment profile active model differs from the validated winner.")
    candidate = candidate_configuration(selected, candidate_registry)
    if comparison_artifact.get("selected_model_parameters_sha256") != candidate["parameters_sha256"]:
        raise ValueError("Selected-model parameter hash differs from the candidate registry.")
    return build_candidate_estimator(selected, candidate_registry)
