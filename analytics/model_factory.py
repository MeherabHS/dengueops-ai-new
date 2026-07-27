"""Authoritative construction and validation for governed learned models."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

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


@dataclass(frozen=True)
class TrustedModelAdapter:
    """Code-controlled execution contract for one governed registry identity."""

    candidate_class: str
    model_family: str
    estimator_library: str
    estimator_library_version: str
    preprocessing_type: str
    output_domain_rule: str
    parameter_names: frozenset[str]
    builder: Callable[[dict[str, Any]], Any] | None


def _pipeline(model: Any) -> Pipeline:
    return Pipeline([("scaler", StandardScaler()), ("model", model)])


TRUSTED_MODEL_ADAPTERS: dict[str, TrustedModelAdapter] = {
    "moving_average_4w": TrustedModelAdapter(
        "comparison_baseline", "MovingAverage4W", "dengueops",
        "checkpoint-dd2fc901c1c0467481c4dfa8e284f6ef2d8e3979", "none",
        "nonnegative_source_expected_fail_if_invalid",
        frozenset({"prediction_source", "window_weeks"}), None,
    ),
    "seasonal_naive_52w": TrustedModelAdapter(
        "comparison_baseline", "SeasonalNaive52W", "dengueops",
        "checkpoint-dd2fc901c1c0467481c4dfa8e284f6ef2d8e3979", "none",
        "nonnegative_source_expected_fail_if_invalid",
        frozenset({"seasonal_lag_weeks", "prediction_source"}), None,
    ),
    "ridge_regression": TrustedModelAdapter(
        "learned_model", "Ridge", "scikit-learn", "1.9.0", "StandardScaler",
        "preserve_raw_and_clip_published_at_zero", frozenset({"alpha", "fit_intercept", "solver"}),
        lambda parameters: _pipeline(Ridge(**parameters)),
    ),
    "poisson_regression": TrustedModelAdapter(
        "learned_model", "PoissonRegressor", "scikit-learn", "1.9.0", "StandardScaler",
        "negative_or_nonfinite_output_fails_fold",
        frozenset({"alpha", "fit_intercept", "max_iter", "tol"}),
        lambda parameters: _pipeline(PoissonRegressor(**parameters)),
    ),
    "random_forest": TrustedModelAdapter(
        "learned_model", "RandomForestRegressor", "scikit-learn", "1.9.0", "none",
        "nonnegative_training_targets_expected_fail_if_invalid",
        frozenset({"n_estimators", "max_depth", "min_samples_leaf", "max_features", "bootstrap", "random_state", "n_jobs", "criterion"}),
        lambda parameters: RandomForestRegressor(**parameters),
    ),
    "gradient_boosting": TrustedModelAdapter(
        "learned_model", "GradientBoostingRegressor", "scikit-learn", "1.9.0", "none",
        "preserve_raw_and_clip_published_at_zero",
        frozenset({"loss", "learning_rate", "n_estimators", "subsample", "min_samples_leaf", "max_depth", "random_state"}),
        lambda parameters: GradientBoostingRegressor(**parameters),
    ),
    "elastic_net": TrustedModelAdapter(
        "learned_model", "ElasticNet", "scikit-learn", "1.9.0", "StandardScaler",
        "preserve_raw_and_clip_published_at_zero",
        frozenset({"alpha", "l1_ratio", "fit_intercept", "precompute", "max_iter", "copy_X", "tol", "warm_start", "positive", "selection"}),
        lambda parameters: _pipeline(ElasticNet(**parameters)),
    ),
    "negative_binomial_regression": TrustedModelAdapter(
        "learned_model", "StatsmodelsNegativeBinomialNB2", "statsmodels", "0.14.6", "StandardScaler",
        "negative_or_nonfinite_output_fails_fold",
        frozenset({"loglike_method", "fit_intercept", "optimizer", "max_iter", "gtol", "full_output", "disp", "check_rank", "missing", "dispersion"}),
        lambda parameters: StatsmodelsNegativeBinomialNB2(**parameters),
    ),
    "extra_trees": TrustedModelAdapter(
        "learned_model", "ExtraTreesRegressor", "scikit-learn", "1.9.0", "none",
        "nonnegative_training_targets_expected_fail_if_invalid",
        frozenset({"n_estimators", "criterion", "max_depth", "min_samples_split", "min_samples_leaf", "max_features", "bootstrap", "random_state", "n_jobs", "warm_start"}),
        lambda parameters: ExtraTreesRegressor(**parameters),
    ),
    "hist_gradient_boosting": TrustedModelAdapter(
        "learned_model", "HistGradientBoostingRegressor", "scikit-learn", "1.9.0", "none",
        "preserve_raw_and_clip_published_at_zero",
        frozenset({"loss", "learning_rate", "max_iter", "max_leaf_nodes", "max_depth", "min_samples_leaf", "l2_regularization", "max_bins", "early_stopping", "tol", "random_state"}),
        lambda parameters: HistGradientBoostingRegressor(**parameters),
    ),
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


def candidate_ids(registry: dict) -> tuple[str, ...]:
    return tuple(str(candidate["model_id"]) for candidate in registry.get("candidates", []))


def learned_model_ids(registry: dict) -> tuple[str, ...]:
    return tuple(
        str(candidate["model_id"]) for candidate in registry.get("candidates", [])
        if candidate.get("candidate_class") == "learned_model"
    )


def baseline_model_ids(registry: dict) -> tuple[str, ...]:
    return tuple(
        str(candidate["model_id"]) for candidate in registry.get("candidates", [])
        if candidate.get("candidate_class") == "comparison_baseline"
    )


def selectable_learned_model_ids(registry: dict) -> tuple[str, ...]:
    return tuple(
        str(candidate["model_id"]) for candidate in registry.get("candidates", [])
        if candidate.get("candidate_class") == "learned_model"
        and candidate.get("selection_role") == "learned_selectable"
        and candidate.get("selectable") is True
    )


def trusted_adapter(model_id: str) -> TrustedModelAdapter:
    descriptor = TRUSTED_MODEL_ADAPTERS.get(model_id)
    if descriptor is None:
        raise ValueError(f"Candidate {model_id} has no trusted model adapter.")
    return descriptor


def _validate_adapter_parameters(
    model_id: str, descriptor: TrustedModelAdapter, parameters: dict[str, Any]
) -> None:
    if set(parameters) != set(descriptor.parameter_names):
        raise ValueError(f"Unsupported parameter contract for {model_id}.")
    if descriptor.builder is None:
        integers = (
            ("window_weeks",) if model_id == "moving_average_4w"
            else ("seasonal_lag_weeks",)
        )
        if not isinstance(parameters.get("prediction_source"), str) or any(
            not isinstance(parameters.get(name), int)
            or isinstance(parameters.get(name), bool)
            or int(parameters[name]) < 1
            for name in integers
        ):
            raise ValueError(f"Unsupported governed parameters for {model_id}.")
        return
    try:
        estimator = descriptor.builder(dict(parameters))
        validated = estimator.named_steps["model"] if isinstance(estimator, Pipeline) else estimator
        validate = getattr(validated, "_validate_params", None)
        if callable(validate):
            validate()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported governed parameters for {model_id}.") from exc


def validate_candidate_configuration(candidate: dict, registry: dict | None = None) -> dict:
    """Validate one frozen learned-model configuration without constructing it."""
    errors: list[str] = []
    model_id = candidate.get("model_id")
    descriptor = TRUSTED_MODEL_ADAPTERS.get(str(model_id))
    if descriptor is None or descriptor.candidate_class != "learned_model":
        errors.append(f"Unsupported learned candidate: {model_id}.")
    historical = candidate.get("enabled") is True and "candidate_class" not in candidate
    if not historical:
        if candidate.get("candidate_class") != "learned_model" or candidate.get("selection_role") != "learned_selectable":
            errors.append(f"Candidate {model_id} is not a selectable learned model.")
        if candidate.get("selectable") is not True:
            errors.append(f"Candidate {model_id} is not selectable.")
    if candidate.get("parameters_sha256") != canonical_sha256(candidate.get("parameters", {})):
        errors.append(f"Parameter hash mismatch for {model_id}.")
    parameters = candidate.get("parameters", {})
    if descriptor is not None:
        try:
            _validate_adapter_parameters(str(model_id), descriptor, parameters)
        except ValueError as exc:
            errors.append(str(exc))
    preprocessing = candidate.get("preprocessing", {})
    expected_preprocessing = descriptor.preprocessing_type if descriptor is not None else None
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
    if descriptor is not None and not historical:
        identity = (
            candidate.get("model_family"),
            candidate.get("estimator_library"),
            candidate.get("estimator_library_version"),
        )
        if identity != (
            descriptor.model_family,
            descriptor.estimator_library,
            descriptor.estimator_library_version,
        ):
            errors.append(f"Frozen estimator identity mismatch for {model_id}.")
        if candidate.get("output_domain_rule") != descriptor.output_domain_rule:
            errors.append(f"Unsupported output-domain rule for {model_id}.")
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
    for candidate in registry.get("candidates", []):
        descriptor = TRUSTED_MODEL_ADAPTERS.get(str(candidate.get("model_id")))
        if descriptor is None:
            errors.append(f"Candidate {candidate.get('model_id')} has no trusted model adapter.")
        elif descriptor.candidate_class != candidate.get("candidate_class"):
            errors.append(f"Candidate class does not match trusted adapter for {candidate.get('model_id')}.")
    forbidden: list[str] = []
    _find_forbidden_tuning_fields(registry, forbidden)
    if forbidden:
        errors.append(f"Tuning fields are prohibited: {', '.join(sorted(set(forbidden)))}.")
    if registry.get("feature_order_sha256") != canonical_sha256(list(FEATURE_COLUMNS)):
        errors.append("Candidate registry feature order mismatch.")
    if errors:
        raise ValueError(" ".join(dict.fromkeys(errors)))
    learned = learned_model_ids(registry)
    baselines = baseline_model_ids(registry)
    if not learned or not baselines or len(learned) + len(baselines) != len(ids):
        raise ValueError("Current registry must define learned candidates and comparison baselines.")
    for candidate in registry["candidates"]:
        if candidate["candidate_class"] == "learned_model":
            validate_candidate_configuration(candidate, registry)
        else:
            model_id = candidate.get("model_id")
            descriptor = trusted_adapter(str(model_id))
            if candidate.get("candidate_class") != "comparison_baseline" or candidate.get("selection_role") != "baseline_only" or candidate.get("selectable") is not False:
                raise ValueError(f"Baseline {model_id} must be comparison-only and non-selectable.")
            if candidate.get("parameters_sha256") != canonical_sha256(candidate.get("parameters", {})):
                raise ValueError(f"Parameter hash mismatch for {model_id}.")
            _validate_adapter_parameters(str(model_id), descriptor, candidate.get("parameters", {}))
            if candidate.get("preprocessing_identity") != canonical_sha256(candidate.get("preprocessing", {})):
                raise ValueError(f"Preprocessing identity mismatch for {model_id}.")
            if candidate.get("feature_order_sha256") != registry.get("feature_order_sha256"):
                raise ValueError(f"Candidate feature order mismatch for {model_id}.")
            identity = (candidate.get("model_family"), candidate.get("estimator_library"), candidate.get("estimator_library_version"))
            expected = (descriptor.model_family, descriptor.estimator_library, descriptor.estimator_library_version)
            if identity != expected or candidate.get("preprocessing", {}).get("type") != descriptor.preprocessing_type \
                    or candidate.get("output_domain_rule") != descriptor.output_domain_rule:
                raise ValueError(f"Baseline trusted adapter identity mismatch for {model_id}.")
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
    descriptor = trusted_adapter(model_id)
    if descriptor.builder is None:
        raise ValueError(f"Candidate {model_id} is not a learned estimator.")
    parameters = dict(candidate["parameters"])
    try:
        return descriptor.builder(parameters)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported governed parameters for {model_id}.") from exc


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
