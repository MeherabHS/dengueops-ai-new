"""Governed P1.2B selected-model adoption and final forecast publication."""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import sklearn

sys.path.insert(0, str(Path(__file__).parent))
from deployment_profiles import load_deployment_profile, validate_model_card_against_profile
from explainability_engine import (SELECTED_OUTPUT_PATH, build_selected_model_explainability,
                                   validate_selected_model_explainability)
from feature_engineering import (DEFAULT_OUTPUT_PATH as FEATURES_CSV, FEATURE_COLUMNS,
                                 build_features, build_inference_features)
from formula_registry import build_formula_metadata, current_deployment_gate, get_parameter
from model_candidates import (COMPARISON_SCHEMA_PATH, OUTPUT_PATH as COMPARISON_OUTPUT,
                              select_comparison_winner, validate_comparison_artifact)
from model_factory import (build_active_forecast_estimator, build_candidate_estimator,
                           candidate_configuration, file_sha256,
                           load_and_validate_candidate_registry)
from provenance import (artifact_provenance, assert_same_provenance, derive_data_mode,
                        provenance_from_feature_frame)
from uncertainty_engine import (LEGACY_STATUS, METHOD_ID as UNCERTAINTY_METHOD_ID,
    METHOD_VERSION as UNCERTAINTY_METHOD_VERSION, UNCERTAINTY_PATH,
    UNCERTAINTY_STATUS, build_uncertainty_artifact, validate_and_load_rf_residuals,
    validate_uncertainty_artifact)
from validation_backtest import (ROLLING_VALIDATION_OUTPUT, TARGET_COL,
                                 load_feature_matrix as load_backtest_features,
                                 validate_rolling_validation)

ROOT = Path(__file__).resolve().parent.parent
FORECAST_OUTPUT = ROOT / "data" / "forecast_output.json"
MODEL_CARD_OUTPUT = ROOT / "data" / "model_card.json"
VALIDATION_OUTPUT = ROOT / "data" / "validation_metrics.json"
LEGACY_EXPLAINABILITY_OUTPUT = ROOT / "data" / "model_explainability.json"
REGISTRY_PATH = ROOT / "config" / "candidate_models_p1.2a-v1.json"
FORMULA_PATH = ROOT / "config" / "formulas.json"
EVIDENCE_PATH = ROOT / "config" / "evidence_registry.json"
TARGET_COL = "target_cases_next_2w"
HORIZON_DAYS = 14
ADOPTION_STATUS = "adopted_p1.2b"
ADOPTION_POLICY_VERSION = "p1.2b-v1"
ACTIVE_MODEL_ID = "random_forest"
REPORTING_ROUNDING_POLICY = "nearest_integer_python_round_half_to_even"

RISK_THRESHOLDS = [
    (float(get_parameter("FORECAST.GROWTH_CATEGORY", "moderate_start")), "Low"),
    (float(get_parameter("FORECAST.GROWTH_CATEGORY", "high_start")), "Moderate"),
    (float(get_parameter("FORECAST.GROWTH_CATEGORY", "very_high_start")), "High"),
    (float("inf"), "Critical"),
]
GROWTH_CATEGORY_LABELS = {"Low": "Low forecast growth", "Moderate": "Moderate forecast growth",
                          "High": "High forecast growth", "Critical": "Very high forecast growth"}
FORECAST_FORMULA_IDS = (
    "TARGET.HORIZON.2W", "FEATURE.CASE_LAGS", "FEATURE.CLIMATE_LAGS",
    "FEATURE.CASE_ROLLING", "FEATURE.GROWTH_RATIOS", "FEATURE.SEASONAL_CYCLIC",
    "FEATURE.SEASON_FLAGS", "MODEL.SELECTED_MODEL_ADOPTION", "MODEL.BASELINE.NAIVE",
    "MODEL.BASELINE.MA4", "FORECAST.GROWTH_FACTOR", "FORECAST.GROWTH_CATEGORY",
    "FORECAST.GROWTH_SCORE", "FORECAST.RMSE_SENSITIVITY", "UNCERTAINTY.TEMPORAL_CALIBRATION",
)
FEATURE_FORMULA_IDS = FORECAST_FORMULA_IDS[:7]


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def classify_risk(growth_factor: float) -> tuple[str, int]:
    gf = max(0.0, growth_factor)
    if gf < 1.0: score = gf * 32.0
    elif gf < 1.10: score = 32.0 + (gf - 1.0) / 0.10 * 3.0
    elif gf < 1.50: score = 35.0 + (gf - 1.10) / 0.40 * 25.0
    elif gf < 2.00: score = 60.0 + (gf - 1.50) / 0.50 * 25.0
    else: score = 85.0 + (gf - 2.00) * 10.0
    risk_score = max(0, min(100, round(score)))
    risk_level = next(level for threshold, level in RISK_THRESHOLDS if gf < threshold)
    return risk_level, risk_score


def compute_growth_factor(forecast_cases: float, reference_cases: float) -> float:
    if reference_cases <= 0:
        return float(get_parameter("FORECAST.GROWTH_FACTOR", "zero_reference_default"))
    value = forecast_cases / reference_cases
    return round(max(float(get_parameter("FORECAST.GROWTH_FACTOR", "minimum")),
                     min(float(get_parameter("FORECAST.GROWTH_FACTOR", "maximum")), value)), 3)


def advance_epi_week(epi_year: int, epi_week: int, weeks: int) -> tuple[int, int]:
    if not 1 <= epi_week <= 52:
        raise ValueError("epi_week must be between 1 and 52.")
    zero_based = epi_week - 1 + weeks
    return epi_year + zero_based // 52, zero_based % 52 + 1


def load_feature_matrix() -> pd.DataFrame:
    if FEATURES_CSV.exists():
        return pd.read_csv(FEATURES_CSV).sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    return build_features()[0]


def load_inference_matrix() -> pd.DataFrame:
    return build_inference_features()


def _validate_targets_and_features(df: pd.DataFrame) -> None:
    if len(FEATURE_COLUMNS) != 18 or list(df.loc[:, FEATURE_COLUMNS].columns) != list(FEATURE_COLUMNS):
        raise ValueError("Final forecast requires exactly 18 features in canonical order.")
    values = df.loc[:, FEATURE_COLUMNS].to_numpy(dtype=float)
    targets = df.loc[:, TARGET_COL].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not np.isfinite(targets).all() or (targets < 0).any():
        raise ValueError("Final forecast requires finite features and finite nonnegative targets.")


def train_final_model(df: pd.DataFrame, registry: dict | None = None):
    """Fit a fresh governed Random Forest on every labelled row."""
    registry = registry or load_and_validate_candidate_registry()[0]
    _validate_targets_and_features(df)
    model = build_candidate_estimator(ACTIVE_MODEL_ID, registry)
    model.fit(df.loc[:, FEATURE_COLUMNS].to_numpy(), df.loc[:, TARGET_COL].to_numpy())
    return model


def generate_forecast(training_df: pd.DataFrame, inference_row: pd.Series, model: Any,
                      provenance: dict | None = None, governance: Mapping[str, Any] | None = None) -> dict:
    _validate_targets_and_features(training_df)
    if list(inference_row.loc[FEATURE_COLUMNS].index) != list(FEATURE_COLUMNS):
        raise ValueError("Inference feature order differs from the canonical order.")
    x_latest = inference_row.loc[FEATURE_COLUMNS].to_numpy(dtype=float).reshape(1, -1)
    if not np.isfinite(x_latest).all():
        raise ValueError("Inference row contains non-finite model inputs.")
    latest_training = training_df.iloc[-1]
    if (int(latest_training["epi_year"]), int(latest_training["epi_week"])) > (
            int(inference_row["epi_year"]), int(inference_row["epi_week"])):
        raise ValueError("Training cutoff cannot be later than the forecast inference origin.")
    raw = float(model.predict(x_latest)[0])
    if not math.isfinite(raw):
        raise ValueError("Selected-model prediction is non-finite.")
    is_random_forest = model.__class__.__name__ == "RandomForestRegressor"
    if is_random_forest and raw < 0:
        raise ValueError("Negative Random Forest prediction violates the governed invariant.")
    published = max(0.0, raw)
    forecast_cases = int(round(published))
    reference = float(inference_row["cases_rolling_4w"])
    growth = compute_growth_factor(forecast_cases, reference)
    risk_level, risk_score = classify_risk(growth)
    target_year, target_week = advance_epi_week(int(inference_row["epi_year"]), int(inference_row["epi_week"]), 2)
    latest = training_df.iloc[-1]
    governance = dict(governance or {})
    model_id = governance.get("active_model_id", ACTIVE_MODEL_ID if is_random_forest else model.__class__.__name__)
    result = {
        "forecast_id": 1, "date_generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_known_epi_year": int(inference_row["epi_year"]), "latest_known_epi_week": int(inference_row["epi_week"]),
        "training_cutoff_epi_year": int(latest["epi_year"]), "training_cutoff_epi_week": int(latest["epi_week"]),
        "target_epi_year": target_year, "target_epi_week": target_week, "horizon_days": HORIZON_DAYS,
        "target": TARGET_COL, "forecast_origin": {"epi_year": int(inference_row["epi_year"]), "epi_week": int(inference_row["epi_week"])},
        "training_cutoff": {"epi_year": int(latest["epi_year"]), "epi_week": int(latest["epi_week"])},
        "training_rows": len(training_df), "city": str(inference_row["city"]),
        "forecast_cases": forecast_cases, "raw_prediction": raw, "published_prediction": published,
        "clipping_applied": raw != published, "reporting_rounding_policy": REPORTING_ROUNDING_POLICY,
        "growth_factor": growth, "experimental_growth_score": risk_score,
        "forecast_growth_category": GROWTH_CATEGORY_LABELS[risk_level],
        "growth_category_status": "unsupported_provisional", "model_name": model.__class__.__name__,
        "active_model_id": model_id, "current_forecast_model": model_id,
        "model_family": governance.get("model_family", model.__class__.__name__),
        "estimator_library": "scikit-learn", "estimator_library_version": sklearn.__version__,
        "model_params": governance.get("model_parameters", {}),
        "adopted_model_parameters_sha256": governance.get("adopted_model_parameters_sha256"),
        "candidate_registry_sha256": governance.get("candidate_registry_sha256"),
        "comparison_artifact_sha256": governance.get("comparison_artifact_sha256"),
        "comparison_selected_model": governance.get("comparison_selected_model", model_id),
        "adoption_status": governance.get("adoption_status", ADOPTION_STATUS if is_random_forest else "uncommitted"),
        "adoption_policy_version": governance.get("adoption_policy_version", ADOPTION_POLICY_VERSION),
        "features_used": list(FEATURE_COLUMNS), "reference_cases_4w_rolling": round(reference, 1),
        "latest_observed_cases": int(inference_row["cases"]),
        "baseline_context": {"naive_forecast": max(0, int(round(inference_row["cases_lag_1w"]))),
                             "moving_average_forecast": max(0, int(round(inference_row["cases_rolling_4w"])))},
        "notes": ["Forecast trained on all available labelled feature rows.",
                  "Inference uses the unchanged latest target-independent feature row.",
                  "Random Forest was selected using deterministic synthetic comparison evidence; no real-world superiority is claimed."],
    }
    result.update(build_formula_metadata(FORECAST_FORMULA_IDS, current_deployment_gate()))
    if provenance is not None:
        result["provenance"] = dict(provenance)
        result["data_mode"] = derive_data_mode(provenance)
    return result


def _scenario(label: str, cases: int, reference: float) -> dict:
    growth = compute_growth_factor(cases, reference); risk, score = classify_risk(growth)
    return {"label": label, "forecast_cases": cases, "growth_factor": growth,
            "experimental_growth_score": score,
            "forecast_growth_category": GROWTH_CATEGORY_LABELS[risk]}


def bind_selected_model_uncertainty(forecast: dict, rmse: float, candidate: Mapping[str, Any],
                                    validation_matrix_hash: str) -> dict:
    if forecast.get("active_model_id") != ACTIVE_MODEL_ID or candidate.get("model_id") != ACTIVE_MODEL_ID:
        raise ValueError("Uncertainty model binding differs from the active Random Forest.")
    if not math.isfinite(rmse) or rmse < 0:
        raise ValueError("Selected-model RMSE is invalid.")
    point = int(forecast["forecast_cases"]); reference = float(forecast["reference_cases_4w_rolling"])
    legacy_binding = {
        "method": "legacy_selected_model_rmse_sensitivity_band", "model_id": ACTIVE_MODEL_ID,
        "model_family": candidate["model_family"], "model_parameters_sha256": candidate["parameters_sha256"],
        "validation_split": "legacy_final_chronological_20_percent_138_train_35_validation",
        "validation_matrix_sha256": validation_matrix_hash, "rmse": rmse, "legacy": True,
        "calibrated": False, "is_prediction_interval": False, "calibration_pending_phase": "P1.3",
    }
    scenarios = {
        "best_case": _scenario("Lower sensitivity scenario", max(0, int(round(point-rmse))), reference),
        "expected_case": _scenario("Point forecast", point, reference),
        "worst_case": _scenario("Upper sensitivity scenario", int(round(point+rmse)), reference),
    }
    forecast["preparedness_scenarios"] = scenarios
    forecast["preparedness_scenario_method"] = {
        "type": "legacy_rf_rmse_planning_sensitivity", "source": "selected_random_forest_legacy_holdout",
        "model": "RandomForestRegressor", "rmse": rmse, "uncertainty_pct": round(rmse / point * 100, 1) if point else None,
        "status": LEGACY_STATUS, "calibrated": False, "is_prediction_interval": False,
        "model_binding": legacy_binding,
        "note": "Legacy RF RMSE planning sensitivity for operational compatibility only; it is not active forecast uncertainty.",
    }
    forecast["uncertainty_scenarios"] = scenarios
    forecast["uncertainty_scenarios_deprecation"] = {
        "deprecated": True, "authoritative_field": "preparedness_scenarios",
        "status": "compatibility_alias_only_not_forecast_uncertainty",
    }
    return forecast


def validate_selected_model_adoption(comparison: dict, comparison_sha256: str, rolling: dict,
                                     rolling_sha256: str, registry: dict, registry_sha256: str,
                                     profile: dict, provenance: dict) -> dict:
    """Independently recompute and validate every identity before fitting the active model."""
    validate_comparison_artifact(comparison, expected_registry_sha256=registry_sha256,
                                 expected_rolling_sha256=rolling_sha256, expected_rolling=rolling)
    errors: list[str] = []
    if registry_sha256 != profile["candidate_comparison"]["candidate_registry_sha256"]:
        errors.append("Candidate registry hash differs from the deployment profile.")
    if comparison.get("candidate_registry_sha256") != registry_sha256:
        errors.append("Comparison candidate registry hash mismatch.")
    if comparison.get("rolling_validation_artifact_sha256") != rolling_sha256:
        errors.append("Comparison rolling-validation hash mismatch.")
    expected = {
        "formula_registry_version": profile["formula_registry_version"],
        "formula_registry_sha256": profile["formula_registry_sha256"],
        "deployment_profile_sha256": provenance["deployment_profile_sha256"],
        "evidence_registry_sha256": provenance["evidence_registry_sha256"],
    }
    for key, value in expected.items():
        if comparison.get(key) != value:
            errors.append(f"Comparison {key} mismatch.")
    for key in ("run_id", "input_manifest_sha256"):
        if comparison.get("provenance", {}).get(key) != provenance.get(key):
            errors.append(f"Comparison provenance {key} mismatch.")
    winner, _, eligible = select_comparison_winner(comparison.get("aggregate_metrics", {}), registry["candidates"])
    stored = comparison.get("comparison_selected_model")
    if winner != stored or winner != ACTIVE_MODEL_ID:
        errors.append("Independently recomputed winner is not the governed Random Forest target.")
    if comparison.get("selection_status") != "comparison_complete_not_adopted":
        errors.append("Comparison selection status is not complete.")
    if comparison.get("adoption_status") != "not_adopted_p1.2a":
        errors.append("Input comparison is not in the P1.2A non-adopted state.")
    if comparison.get("current_forecast_model") != "gradient_boosting":
        errors.append("Input comparison does not retain its historical P1.2A active-model identity.")
    metrics = comparison.get("aggregate_metrics", {}).get(ACTIVE_MODEL_ID, {})
    if metrics.get("successful_folds") != 68 or metrics.get("failed_folds") != 0:
        errors.append("Random Forest did not complete all 68 folds successfully.")
    if ACTIVE_MODEL_ID not in eligible or comparison.get("selection_eligibility", {}).get(ACTIVE_MODEL_ID) is not True:
        errors.append("Random Forest is not selection-eligible.")
    candidate = candidate_configuration(ACTIVE_MODEL_ID, registry)
    if comparison.get("selected_model_parameters_sha256") != candidate["parameters_sha256"]:
        errors.append("Random Forest parameter hash mismatch.")
    if profile["candidate_comparison"].get("adoption_target_model") != ACTIVE_MODEL_ID:
        errors.append("Deployment profile adoption target mismatch.")
    if registry.get("target") != TARGET_COL or registry.get("horizon_weeks") != 2:
        errors.append("Registry target or horizon mismatch.")
    if rolling.get("fold_count") != 68 or rolling.get("target") != TARGET_COL or rolling.get("horizon_weeks") != 2:
        errors.append("Rolling fold, target, or horizon mismatch.")
    if errors:
        raise ValueError(" ".join(dict.fromkeys(errors)))
    return candidate


def build_model_card(profile: dict, provenance: dict, validation: dict, training_df: pd.DataFrame,
                     legacy_explainability: dict, legacy_explainability_sha256: str,
                     rolling: dict, rolling_sha256: str, comparison: dict, comparison_sha256: str,
                     selected_explainability: dict, selected_explainability_sha256: str,
                     forecast_sha256: str, uncertainty: dict, uncertainty_sha256: str) -> dict:
    first, last = training_df.iloc[0], training_df.iloc[-1]
    active_metrics = comparison["aggregate_metrics"][ACTIVE_MODEL_ID]
    mandatory = "Random Forest was selected under the declared P1.2A comparison rule using deterministic synthetic rolling-origin folds and was adopted as the active demonstration model. This does not establish real-world Dhaka superiority."
    card = {
        "model_card_schema_version": (
            "1.1" if profile["deprecated_compatibility_fields"]["status"] == "resolved" else "1.0"
        ), "model_card_id": profile["model"]["model_card_id"],
        "model_card_version": profile["model"]["model_card_version"], "model_id": ACTIVE_MODEL_ID,
        "model_version": profile["model"]["model_version"], "deployment_id": profile["deployment_id"],
        "model_family": "RandomForestRegressor", "active_model_family": "RandomForestRegressor",
        "estimator_library": "scikit-learn", "active_model_library": "scikit-learn",
        "estimator_library_version": sklearn.__version__, "active_model_library_version": sklearn.__version__,
        "target": TARGET_COL, "forecast_horizon": {"value": 14, "unit": "days"},
        "feature_formula_ids": list(FEATURE_FORMULA_IDS), "selected_features": list(FEATURE_COLUMNS),
        "training_period": {"start": {"epi_year": int(first.epi_year), "epi_week": int(first.epi_week)},
                            "end": {"epi_year": int(last.epi_year), "epi_week": int(last.epi_week)}},
        "data_sources": {"cases": provenance["case_source"], "climate": provenance["climate_source"], "operational": provenance["operational_source"]},
        "data_mode": profile["data_mode"], "observed_data_mode": profile["observed_data_mode"],
        "validation_method": "expanding_window_rolling_origin_candidate_comparison",
        "baseline_models": ["previous_week_naive", "moving_average_4w", "seasonal_naive_52w"],
        "performance_metrics": {"active_random_forest_rolling": active_metrics,
                                "legacy_gbr_holdout": validation["metrics"].get("gradient_boosting", {}),
                                "legacy_gbr_rolling": rolling["aggregate_metrics"].get("gradient_boosting", {}),
                                "selected_random_forest_holdout": {"rmse": uncertainty["retained_legacy_rmse"]["rmse"]}},
        "model_selection_status": "comparison_complete_and_adopted", "comparison_selected_model": ACTIVE_MODEL_ID,
        "current_forecast_model": ACTIVE_MODEL_ID, "selected_model_adoption_status": ADOPTION_STATUS,
        "adoption_status": ADOPTION_STATUS, "adoption_policy_version": ADOPTION_POLICY_VERSION,
        "adopted_model_parameters_sha256": profile["model"]["model_parameters_sha256"],
        "candidate_model_comparison_artifact_path": "data/candidate_model_comparison.json",
        "candidate_model_comparison_artifact_sha256": comparison_sha256,
        "comparison_artifact_sha256": comparison_sha256,
        "candidate_registry_version": profile["candidate_comparison"]["candidate_registry_version"],
        "candidate_registry_sha256": comparison["candidate_registry_sha256"],
        "candidate_models": profile["candidate_comparison"]["enabled_candidate_ids"],
        "primary_selection_metric": "MAE", "selection_rule": "lowest rolling-origin MAE among candidates completing all 68 folds; deterministic declared tie sequence",
        "comparison_selected_model_reason": comparison["comparison_selected_model_reason"], "selected_model_rank": 1,
        "selected_model_fold_count": 68, "selected_model_failures": 0, "comparison_limitations": comparison["limitations"],
        "primary_validation_method": "expanding_window_rolling_origin", "rolling_validation_artifact_path": "data/rolling_validation.json",
        "rolling_validation_artifact_sha256": rolling_sha256, "rolling_validation_version": rolling["validation_version"],
        "rolling_fold_count": 68, "rolling_initial_training_window": rolling["initial_training_window"],
        "rolling_step_weeks": 1, "rolling_horizon_weeks": 2,
        "rolling_aggregate_metrics": active_metrics, "rolling_baseline_comparison": comparison.get("wins_ties_losses", {}),
        "performance_variability": {"source": "candidate_model_comparison.json", "active_model": ACTIVE_MODEL_ID},
        "native_importance_stability_status": "not_evaluated_across_temporal_folds",
        "permutation_stability_status": "not_evaluated_single_row_folds",
        "legacy_validation_method": "time_based_holdout_final_20_percent", "legacy_validation_artifact_path": "data/validation_metrics.json",
        "validation_limitations": ["Active rolling metrics come from the validated P1.2A candidate comparison.", "P1.1 GBR rolling metrics are historical compatibility evidence only."],
        "uncertainty_method": UNCERTAINTY_METHOD_ID,
        "uncertainty_method_version": UNCERTAINTY_METHOD_VERSION,
        "uncertainty_status": UNCERTAINTY_STATUS,
        "nominal_coverage": uncertainty["nominal_coverage"],
        "observed_temporal_coverage": uncertainty["historical_evaluation"]["aggregate_metrics"]["observed_coverage"],
        "covered_fold_count": uncertainty["historical_evaluation"]["aggregate_metrics"]["covered_fold_count"],
        "evaluated_fold_count": uncertainty["historical_evaluation"]["aggregate_metrics"]["evaluated_fold_count"],
        "calibration_warmup_fold_count": 20,
        "interval_width_summary": {key: uncertainty["historical_evaluation"]["aggregate_metrics"][key] for key in
            ("average_interval_width", "median_interval_width", "minimum_interval_width", "maximum_interval_width")},
        "lower_miss_count": uncertainty["historical_evaluation"]["aggregate_metrics"]["lower_miss_count"],
        "upper_miss_count": uncertainty["historical_evaluation"]["aggregate_metrics"]["upper_miss_count"],
        "uncertainty_artifact_path": "data/forecast_uncertainty.json",
        "uncertainty_artifact_sha256": uncertainty_sha256,
        "residual_source_artifact_path": uncertainty["residual_source_artifact_path"],
        "residual_source_artifact_sha256": uncertainty["residual_source_artifact_sha256"],
        "uncertainty_active_model_binding": {"model_id": ACTIVE_MODEL_ID, "model_parameters_sha256": uncertainty["active_model_parameters_sha256"],
            "candidate_registry_sha256": uncertainty["candidate_registry_sha256"], "comparison_artifact_sha256": uncertainty["comparison_artifact_sha256"]},
        "uncertainty_limitations": uncertainty["limitations"],
        "operational_scenario_relationship": uncertainty["operational_scenario_relationship"],
        "retained_legacy_rmse_status": LEGACY_STATUS,
        "is_prediction_interval": False, "calibrated_on_synthetic_data": True,
        "selected_model_explainability_status": "generated_active_selected_model_diagnostic",
        "selected_model_explainability_artifact_path": "data/selected_model_explainability.json",
        "selected_model_explainability_artifact_sha256": selected_explainability_sha256,
        "explainability_status": "generated", "explainability_artifact_path": "data/selected_model_explainability.json",
        "explainability_artifact_sha256": selected_explainability_sha256,
        "explainability_methods": selected_explainability["importance_methods"],
        "explainability_limitations": selected_explainability["limitations"],
        "importance_stability_status": "not_evaluated_across_temporal_folds",
        "explainability_evaluation": {"estimator_role": selected_explainability["estimator_role"],
                                      "training_period": selected_explainability["training_period"],
                                      "validation_period": selected_explainability["validation_period"],
                                      "evaluation_split": selected_explainability["evaluation_split"],
                                      "feature_order_sha256": selected_explainability["feature_order_sha256"],
                                      "validation_matrix_sha256": selected_explainability["validation_matrix_sha256"]},
        "retained_legacy_gbr_evidence": {"status": "historical_compatibility_only_not_active_model_evidence",
                                         "model_explainability_artifact_path": "data/model_explainability.json",
                                         "model_explainability_artifact_sha256": legacy_explainability_sha256,
                                         "rolling_validation_artifact_path": "data/rolling_validation.json",
                                         "validation_metrics_artifact_path": "data/validation_metrics.json"},
        "forecast_artifact_sha256": forecast_sha256,
        "adoption_limitations": [mandatory, "Random Forest cannot extrapolate beyond patterns represented in its training data."],
        "limitations": [mandatory, "Data are deterministic synthetic benchmark data.", "No local calibration or institutional approval exists.",
                        *uncertainty["limitations"],
                        "Use restriction: not for clinical or official public-health use.", *profile["limitations"]],
        "intended_use": profile["intended_use"], "prohibited_uses": profile["prohibited_uses"],
        "maturity_statements": profile["maturity_statements"], "deprecated_compatibility_fields": profile["deprecated_compatibility_fields"],
        "formula_registry_version": profile["formula_registry_version"], "formula_registry_sha256": profile["formula_registry_sha256"],
        "deployment_profile_sha256": provenance["deployment_profile_sha256"],
        "evidence_registry_schema_version": profile["evidence_registry_schema_version"], "evidence_registry_sha256": profile["evidence_registry_sha256"],
        "evidence_ids": profile["evidence_ids"], "approval_record_ids": profile["approval_record_ids"], "approval_status": "not_approved",
        "deployment_gate": profile["deployment_gate"], "provenance": dict(provenance),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return card


def _publish_bundle(selected: dict, uncertainty: dict, forecast: dict, card: dict) -> None:
    """Publish validated exact bytes, with the model card replaced last as commit record."""
    targets = [(SELECTED_OUTPUT_PATH, _json_bytes(selected)), (UNCERTAINTY_PATH, _json_bytes(uncertainty)), (FORECAST_OUTPUT, _json_bytes(forecast)),
               (MODEL_CARD_OUTPUT, _json_bytes(card))]
    old = {path: path.read_bytes() if path.exists() else None for path, _ in targets}
    temps: list[tuple[Path, Path]] = []
    try:
        for path, payload in targets:
            fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload); handle.flush(); os.fsync(handle.fileno())
            if temporary.read_bytes() != payload:
                raise ValueError(f"Temporary artifact byte validation failed for {path.name}.")
            temps.append((path, temporary))
        for path, temporary in temps:
            os.replace(temporary, path)
        if file_sha256(FORECAST_OUTPUT) != card["forecast_artifact_sha256"]:
            raise ValueError("Committed forecast bytes do not match the model card.")
        if file_sha256(SELECTED_OUTPUT_PATH) != card["selected_model_explainability_artifact_sha256"]:
            raise ValueError("Committed explainability bytes do not match the model card.")
        if file_sha256(UNCERTAINTY_PATH) != card["uncertainty_artifact_sha256"]:
            raise ValueError("Committed uncertainty bytes do not match the model card.")
    except Exception:
        for path, payload in old.items():
            if payload is None:
                if path.exists(): path.unlink()
            else:
                fd, name = tempfile.mkstemp(prefix=f".{path.name}.rollback.", suffix=".tmp", dir=path.parent)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(payload); handle.flush(); os.fsync(handle.fileno())
                os.replace(name, path)
        raise
    finally:
        for _, temporary in temps:
            if temporary.exists(): temporary.unlink()


def main() -> None:
    if os.environ.get("DENGUEOPS_MODEL_COMPARISON_STATUS") != "generated":
        raise ValueError("P1.2B adoption requires --run-model-comparison in the current governed pipeline run.")
    training = load_feature_matrix(); inference = load_inference_matrix(); provenance = provenance_from_feature_frame(training)
    assert_same_provenance(provenance, provenance_from_feature_frame(inference), labels=("training", "inference"))
    profile = load_deployment_profile(provenance["deployment_profile_id"])
    registry, registry_sha = load_and_validate_candidate_registry(REGISTRY_PATH)
    comparison_bytes = COMPARISON_OUTPUT.read_bytes(); comparison = json.loads(comparison_bytes.decode("utf-8")); comparison_sha = _sha(comparison_bytes)
    rolling_bytes = ROLLING_VALIDATION_OUTPUT.read_bytes(); rolling = json.loads(rolling_bytes.decode("utf-8")); rolling_sha = _sha(rolling_bytes)
    validate_rolling_validation(rolling, expected_df=training, expected_provenance=provenance)
    candidate = validate_selected_model_adoption(comparison, comparison_sha, rolling, rolling_sha,
                                                 registry, registry_sha, profile, provenance)
    split = int(len(training) * .80); train = training.iloc[:split].copy(); test = training.iloc[split:].copy()
    validation_model = build_candidate_estimator(ACTIVE_MODEL_ID, registry)
    validation_model.fit(train[FEATURE_COLUMNS].to_numpy(), train[TARGET_COL].to_numpy())
    selected = build_selected_model_explainability(validation_model, train, test, FEATURE_COLUMNS, TARGET_COL,
                                                   candidate, provenance, profile, registry_sha, comparison_sha)
    predictions = validation_model.predict(test[FEATURE_COLUMNS].to_numpy())
    if not np.isfinite(predictions).all() or (predictions < 0).any():
        raise ValueError("Selected Random Forest holdout predictions violate finite nonnegative invariants.")
    rmse = float(np.sqrt(np.mean(np.square(test[TARGET_COL].to_numpy() - predictions))))
    final_model = train_final_model(training, registry)
    governance = {"active_model_id": ACTIVE_MODEL_ID, "model_family": candidate["model_family"],
                  "model_parameters": candidate["parameters"], "adopted_model_parameters_sha256": candidate["parameters_sha256"],
                  "candidate_registry_sha256": registry_sha, "comparison_artifact_sha256": comparison_sha,
                  "comparison_selected_model": ACTIVE_MODEL_ID, "adoption_status": ADOPTION_STATUS,
                  "adoption_policy_version": ADOPTION_POLICY_VERSION}
    forecast = generate_forecast(training, inference.iloc[-1], final_model, provenance, governance)
    forecast = bind_selected_model_uncertainty(forecast, rmse, candidate, selected["validation_matrix_sha256"])
    residuals = validate_and_load_rf_residuals(
        comparison, rolling, comparison_sha256=comparison_sha, rolling_sha256=rolling_sha,
        registry_sha256=registry_sha, rf_parameters_sha256=candidate["parameters_sha256"],
        profile=profile, provenance=provenance)
    retained_legacy = {
        "method_id": "legacy_rf_rmse_planning_sensitivity", "rmse": rmse,
        "status": LEGACY_STATUS, "calibrated": False, "is_prediction_interval": False,
        "validation_split": "legacy_final_chronological_20_percent_138_train_35_validation",
        "validation_matrix_sha256": selected["validation_matrix_sha256"],
        "preparedness_values": [forecast["preparedness_scenarios"][key]["forecast_cases"]
                                for key in ("best_case", "expected_case", "worst_case")],
    }
    uncertainty = build_uncertainty_artifact(
        residuals, forecast, comparison_sha256=comparison_sha, rolling_sha256=rolling_sha,
        registry_sha256=registry_sha, candidate=candidate, profile=profile, provenance=provenance,
        retained_legacy_rmse=retained_legacy)
    validate_uncertainty_artifact(uncertainty)
    uncertainty_bytes = _json_bytes(uncertainty); uncertainty_sha = _sha(uncertainty_bytes)
    interval = uncertainty["future_forecast_interval"]; aggregate = uncertainty["historical_evaluation"]["aggregate_metrics"]
    forecast["uncertainty_status"] = UNCERTAINTY_STATUS
    forecast["forecast_uncertainty"] = {
        "method_id": UNCERTAINTY_METHOD_ID, "method_version": UNCERTAINTY_METHOD_VERSION,
        "uncertainty_status": UNCERTAINTY_STATUS, "point_forecast_raw": interval["point_forecast_raw"],
        "interval_lower_raw": interval["lower_raw"], "interval_upper_raw": interval["upper_raw"],
        "point_forecast_reported": interval["point_forecast_reported"],
        "interval_lower_reported": interval["interval_lower_reported"],
        "interval_upper_reported": interval["interval_upper_reported"],
        "lower_clipping_applied": interval["lower_clipping_applied"], "nominal_coverage": 0.9,
        "observed_historical_coverage": aggregate["observed_coverage"], "evaluated_fold_count": 48,
        "uncertainty_artifact_path": "data/forecast_uncertainty.json",
        "uncertainty_artifact_sha256": uncertainty_sha,
        "residual_source_artifact_sha256": comparison_sha, "active_model_id": ACTIVE_MODEL_ID,
        "active_model_parameters_sha256": candidate["parameters_sha256"],
        "is_prediction_interval": False, "calibrated_on_synthetic_data": True,
        "limitations": uncertainty["limitations"],
    }
    selected_bytes = _json_bytes(selected); forecast_bytes = _json_bytes(forecast)
    legacy_bytes = LEGACY_EXPLAINABILITY_OUTPUT.read_bytes(); legacy = json.loads(legacy_bytes.decode("utf-8"))
    validation = json.loads(VALIDATION_OUTPUT.read_text(encoding="utf-8"))
    card = build_model_card(profile, provenance, validation, training, legacy, _sha(legacy_bytes), rolling,
                            rolling_sha, comparison, comparison_sha, selected, _sha(selected_bytes),
                            _sha(forecast_bytes), uncertainty, uncertainty_sha)
    validate_selected_model_explainability(selected, expected_provenance=provenance,
                                           expected_feature_names=FEATURE_COLUMNS, expected_validation_df=test,
                                           expected_comparison_sha256=comparison_sha, expected_registry_sha256=registry_sha)
    validate_model_card_against_profile(card, profile)
    _publish_bundle(selected, uncertainty, forecast, card)
    print(f"Active model: RandomForestRegressor; forecast={forecast['forecast_cases']}; uncertainty={UNCERTAINTY_STATUS}")


if __name__ == "__main__":
    main()
