"""Authoritative construction and validation for governed learned models."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import PoissonRegressor, Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from feature_engineering import FEATURE_COLUMNS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = ROOT / "config" / "candidate_models.json"
REGISTRY_SCHEMA_PATH = ROOT / "config" / "candidate_models.schema.json"
FORBIDDEN_TUNING_FIELDS = {
    "parameter_grid", "search_space", "cross_validation_selector", "trial_count",
    "optimization_objective", "tuning_method",
}
LEARNED_MODEL_IDS = {
    "gradient_boosting", "random_forest", "ridge_regression", "poisson_regression",
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
    if candidate.get("enabled") is not True:
        errors.append(f"Candidate {model_id} is disabled.")
    if candidate.get("parameters_sha256") != canonical_sha256(candidate.get("parameters", {})):
        errors.append(f"Parameter hash mismatch for {model_id}.")
    preprocessing = candidate.get("preprocessing", {})
    expected_preprocessing = {
        "gradient_boosting": "none", "random_forest": "none",
        "ridge_regression": "StandardScaler", "poisson_regression": "StandardScaler",
    }.get(model_id)
    if preprocessing.get("type") != expected_preprocessing:
        errors.append(f"Invalid preprocessing policy for {model_id}.")
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
    if errors:
        raise ValueError(" ".join(dict.fromkeys(errors)))
    return candidate


def load_and_validate_candidate_registry(path: Path = DEFAULT_REGISTRY_PATH) -> tuple[dict, str]:
    """Load exact registry bytes, apply schema and semantic validation, return hash."""
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
        elif candidate.get("parameters_sha256") != canonical_sha256(candidate.get("parameters", {})):
            raise ValueError(f"Parameter hash mismatch for {candidate.get('model_id')}.")
    return registry, hashlib.sha256(payload).hexdigest()


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
