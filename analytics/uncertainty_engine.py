"""Governed P1.3 temporal empirical forecast-range construction and validation."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema

from empirical_range import (
    aggregate_prequential_records as _shared_aggregate,
    build_prequential_evaluation as _shared_prequential_evaluation,
    construct_raw_interval as _shared_construct_raw_interval,
    finite_sample_quantile as _shared_finite_sample_quantile,
)

ROOT = Path(__file__).resolve().parent.parent
FORECAST_PATH = ROOT / "data" / "forecast_output.json"
UNCERTAINTY_PATH = ROOT / "data" / "forecast_uncertainty.json"
MODEL_CARD_PATH = ROOT / "data" / "model_card.json"
SCHEMA_PATH = ROOT / "config" / "forecast_uncertainty.schema.json"

METHOD_ID = "prequential_expanding_absolute_residual_quantile"
METHOD_VERSION = "p1.3-v1"
UNCERTAINTY_STATUS = "temporally_evaluated_synthetic_empirical_range"
NOMINAL_COVERAGE = 0.90
ALPHA = 0.10
WARMUP_FOLDS = 20
EXPECTED_FOLDS = 68
ACTIVE_MODEL_ID = "random_forest"
LEGACY_STATUS = "operational_planning_compatibility_only_not_forecast_interval"
MANDATORY_MEANING = (
    "The empirical range was evaluated using deterministic synthetic rolling-origin Random Forest residuals. "
    "Each evaluated fold used only residuals from earlier folds. Temporal dependence and reuse of the folds for "
    "model selection limit interpretation. This is not evidence of real-world Dhaka calibration. Historical "
    "empirical coverage is not a guarantee of future coverage."
)


def _sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _period_key(value: str) -> tuple[int, int]:
    try:
        year, week = value.split("-W")
        result = (int(year), int(week))
    except Exception as exc:
        raise ValueError(f"Invalid epidemiological period: {value!r}.") from exc
    if result[1] < 1 or result[1] > 52:
        raise ValueError(f"Invalid epidemiological week: {value!r}.")
    return result


def _close(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)


def validate_and_load_rf_residuals(
    comparison: Mapping[str, Any], rolling: Mapping[str, Any], *,
    comparison_sha256: str, rolling_sha256: str, registry_sha256: str,
    rf_parameters_sha256: str, profile: Mapping[str, Any], provenance: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return 68 chronologically joined RF residual records or fail closed."""
    errors: list[str] = []
    predictions = comparison.get("per_fold_predictions", {}).get(ACTIVE_MODEL_ID)
    if not isinstance(predictions, list) or len(predictions) != EXPECTED_FOLDS:
        errors.append("Exactly 68 Random Forest fold prediction records are required.")
        predictions = predictions if isinstance(predictions, list) else []
    rolling_folds = rolling.get("folds")
    if not isinstance(rolling_folds, list) or len(rolling_folds) != EXPECTED_FOLDS:
        errors.append("Exactly 68 rolling fold-reference records are required.")
        rolling_folds = rolling_folds if isinstance(rolling_folds, list) else []
    fold_refs = comparison.get("fold_references")
    if not isinstance(fold_refs, list) or len(fold_refs) != EXPECTED_FOLDS:
        errors.append("Exactly 68 comparison fold references are required.")
        fold_refs = fold_refs if isinstance(fold_refs, list) else []

    def index_unique(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Mapping[str, Any]]:
        values: dict[str, Mapping[str, Any]] = {}
        for row in rows:
            fold_id = str(row.get("fold_id", ""))
            if not fold_id or fold_id in values:
                errors.append(f"{label} contains a missing or duplicate fold ID.")
            else:
                values[fold_id] = row
        return values

    rolling_by_id = index_unique(rolling_folds, "Rolling evidence")
    refs_by_id = index_unique(fold_refs, "Comparison fold references")
    prediction_ids = [str(row.get("fold_id", "")) for row in predictions]
    if len(set(prediction_ids)) != len(prediction_ids) or "" in prediction_ids:
        errors.append("Random Forest predictions contain a missing or duplicate fold ID.")
    if set(prediction_ids) != set(rolling_by_id) or set(prediction_ids) != set(refs_by_id):
        errors.append("RF prediction, rolling-fold, and fold-reference identities differ.")

    if comparison.get("candidate_registry_sha256") != registry_sha256:
        errors.append("Candidate registry hash mismatch in residual source.")
    if comparison.get("rolling_validation_artifact_sha256") != rolling_sha256:
        errors.append("Rolling-validation hash mismatch in comparison residual source.")
    if comparison.get("selected_model_parameters_sha256") != rf_parameters_sha256:
        errors.append("Selected Random Forest parameter hash mismatch.")
    candidate = next((value for value in comparison.get("candidates", [])
                      if value.get("model_id") == ACTIVE_MODEL_ID), None)
    if not candidate or candidate.get("parameters_sha256") != rf_parameters_sha256:
        errors.append("Comparison Random Forest candidate identity is invalid.")
    if profile.get("model", {}).get("model_id") != ACTIVE_MODEL_ID or profile.get("model", {}).get("model_parameters_sha256") != rf_parameters_sha256:
        errors.append("Deployment profile active Random Forest identity mismatch.")
    if comparison.get("comparison_selected_model") != ACTIVE_MODEL_ID:
        errors.append("Comparison-selected model is not Random Forest.")
    if comparison.get("aggregate_metrics", {}).get(ACTIVE_MODEL_ID, {}).get("successful_folds") != EXPECTED_FOLDS:
        errors.append("Random Forest did not complete 68 successful folds.")
    for key in ("run_id", "manifest_sha256", "formula_registry_sha256", "deployment_profile_sha256",
                "evidence_registry_sha256", "candidate_registry_sha256"):
        source = comparison.get("provenance", {}) if key in {"run_id", "manifest_sha256"} else comparison
        if source.get(key) != provenance.get(key):
            errors.append(f"Residual-source provenance {key} mismatch.")
    if rolling.get("provenance") != comparison.get("provenance"):
        errors.append("Rolling and comparison provenance differ.")

    joined: list[dict[str, Any]] = []
    previous_target: tuple[int, int] | None = None
    for expected_index, prediction in enumerate(predictions, start=1):
        fold_id = str(prediction.get("fold_id", ""))
        fold = rolling_by_id.get(fold_id, {})
        ref = refs_by_id.get(fold_id, {})
        if fold.get("fold_index") != expected_index:
            errors.append(f"Fold order/index mismatch for {fold_id}.")
        target_period = str(fold.get("target_period", ""))
        try:
            target_key = _period_key(target_period)
            if previous_target is not None and target_key <= previous_target:
                errors.append("RF residual folds are not in strict chronological order.")
            previous_target = target_key
        except ValueError as exc:
            errors.append(str(exc))
        if prediction.get("fold_status") != "success" or prediction.get("failure_reason") is not None or prediction.get("warnings"):
            errors.append(f"RF fold {fold_id} is failed or warned.")
        try:
            actual = float(prediction["actual"]); raw = float(prediction["raw_prediction"])
            if not math.isfinite(actual) or not math.isfinite(raw):
                raise ValueError
            residual = actual - raw; absolute = abs(residual)
            if not _close(prediction["signed_error"], raw - actual) or not _close(prediction["absolute_error"], absolute):
                errors.append(f"Stored errors do not recompute for {fold_id}.")
        except Exception:
            errors.append(f"RF fold {fold_id} has non-finite or malformed values.")
            continue
        for matrix_key in ("training_matrix_sha256", "validation_matrix_sha256"):
            if ref.get(matrix_key) != fold.get(matrix_key):
                errors.append(f"Fold-reference {matrix_key} mismatch for {fold_id}.")
        joined.append({
            "fold_id": fold_id, "fold_index": expected_index,
            "origin_period": fold.get("origin_period"), "target_period": target_period,
            "training_row_count": fold.get("train_rows"), "actual": actual,
            "raw_prediction": raw, "residual": residual, "absolute_residual": absolute,
            "case_quartile": fold.get("target_volume_quartile"),
            "trajectory_category": fold.get("trajectory"),
            "training_matrix_sha256": ref.get("training_matrix_sha256"),
            "validation_matrix_sha256": ref.get("validation_matrix_sha256"),
        })
    if len(joined) != EXPECTED_FOLDS:
        errors.append("Exactly 68 valid joined RF residuals are required.")
    if errors:
        raise ValueError(" ".join(dict.fromkeys(errors)))
    return joined


def finite_sample_quantile(values: Sequence[float], nominal_coverage: float = NOMINAL_COVERAGE) -> tuple[int, float]:
    return _shared_finite_sample_quantile(values, nominal_coverage)


def construct_raw_interval(point_raw: float, quantile: float) -> dict[str, Any]:
    return _shared_construct_raw_interval(point_raw, quantile)


def _mean(values: Sequence[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def _aggregate(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return _shared_aggregate(records, nominal_coverage=NOMINAL_COVERAGE,
                             warmup_folds=WARMUP_FOLDS, residual_count=EXPECTED_FOLDS)


def build_prequential_evaluation(residuals: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return _shared_prequential_evaluation(
        residuals, expected_folds=EXPECTED_FOLDS, warmup_folds=WARMUP_FOLDS,
        nominal_coverage=NOMINAL_COVERAGE,
    )


def _strata(records: Sequence[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    result = []
    for value in sorted({row[key] for row in records}, key=str):
        rows = [row for row in records if row[key] == value]
        widths = [row["upper_raw"] - row["lower_raw"] for row in rows]
        result.append({"group": value, "count": len(rows),
                       "observed_coverage": sum(row["covered"] for row in rows) / len(rows),
                       "average_interval_width": _mean(widths),
                       "lower_miss_count": sum(row["miss_direction"] == "lower" for row in rows),
                       "upper_miss_count": sum(row["miss_direction"] == "upper" for row in rows),
                       "descriptive_only": True, "small_sample_warning": True})
    return result


def build_uncertainty_artifact(
    residuals: Sequence[Mapping[str, Any]], forecast: Mapping[str, Any], *, comparison_sha256: str,
    rolling_sha256: str, registry_sha256: str, candidate: Mapping[str, Any], profile: Mapping[str, Any],
    provenance: Mapping[str, Any], retained_legacy_rmse: Mapping[str, Any],
) -> dict[str, Any]:
    records, aggregate = build_prequential_evaluation(residuals)
    final_rank, final_quantile = finite_sample_quantile([row["absolute_residual"] for row in residuals])
    point_raw = float(forecast["raw_prediction"]); bounds = construct_raw_interval(point_raw, final_quantile)
    future = {"target_period": f"{forecast['target_epi_year']}-W{int(forecast['target_epi_week']):02d}",
              "residual_pool_count": EXPECTED_FOLDS, "quantile_rank": final_rank,
              "quantile_value": final_quantile, "point_forecast_raw": point_raw, **bounds,
              "point_forecast_reported": int(forecast["forecast_cases"]),
              "interval_lower_reported": math.floor(bounds["lower_raw"]),
              "interval_upper_reported": math.ceil(bounds["upper_raw"]),
              "reporting_policy": "point_nearest_integer_python_round_half_to_even_bounds_outward_floor_ceiling"}
    signed = [row["residual"] for row in residuals]; absolute = [row["absolute_residual"] for row in residuals]
    limitations = [MANDATORY_MEANING,
        "Targets overlap and residuals are temporally dependent.",
        "High-incidence and rising-period performance may be weaker.",
        "The range is not a probability statement and is not a prediction interval.",
        "The deployment remains a synthetic benchmark-only capability demonstration."]
    artifact = {
        "uncertainty_schema_version": "1.0", "uncertainty_artifact_version": METHOD_VERSION,
        "availability_status": "generated", "method_id": METHOD_ID, "method_version": METHOD_VERSION,
        "uncertainty_status": UNCERTAINTY_STATUS, "active_model_id": ACTIVE_MODEL_ID,
        "active_model_family": candidate["model_family"], "active_model_library": candidate["estimator_library"],
        "active_model_library_version": forecast["estimator_library_version"],
        "active_model_parameters_sha256": candidate["parameters_sha256"],
        "candidate_registry_sha256": registry_sha256,
        "comparison_artifact_path": "data/candidate_model_comparison.json", "comparison_artifact_sha256": comparison_sha256,
        "residual_source_artifact_path": "data/candidate_model_comparison.json", "residual_source_artifact_sha256": comparison_sha256,
        "rolling_fold_reference_artifact_path": "data/rolling_validation.json", "rolling_fold_reference_artifact_sha256": rolling_sha256,
        "target": "target_cases_next_2w", "horizon_weeks": 2,
        "feature_order_sha256": profile.get("forecast_uncertainty", {}).get("feature_order_sha256", profile.get("selected_features_sha256", "aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85")),
        "nominal_coverage": NOMINAL_COVERAGE,
        "calibration_design": {"design": "prequential_expanding_window_prior_residuals_only", "residual_definition": "actual_minus_raw_prediction",
            "calibration_score": "absolute_residual", "warmup_fold_count": WARMUP_FOLDS,
            "evaluation_fold_count": EXPECTED_FOLDS-WARMUP_FOLDS, "final_residual_pool_count": EXPECTED_FOLDS,
            "quantile_rank_rule": "min(n, ceil((n + 1) * (1 - alpha)))", "alpha": ALPHA,
            "sorting": "deterministic_ascending", "interpolation": "none", "ties": "retained_as_separate_observations",
            "coverage_rule": "lower_raw <= actual <= upper_raw", "lower_bound_policy": "clip_at_zero_after_raw_construction",
            "rounding_policy": "raw_for_evaluation_outward_floor_lower_ceiling_upper_for_reporting"},
        "residual_summary": {"residual_count": EXPECTED_FOLDS, "signed_residual_minimum": min(signed),
            "signed_residual_maximum": max(signed), "signed_residual_mean": _mean(signed),
            "signed_residual_median": float(statistics.median(signed)), "absolute_residual_minimum": min(absolute),
            "absolute_residual_maximum": max(absolute), "absolute_residual_mean": _mean(absolute),
            "absolute_residual_median": float(statistics.median(absolute))},
        "historical_evaluation": {"records": records, "aggregate_metrics": aggregate},
        "stratified_diagnostics": {"actual_case_quartile": _strata(records, "case_quartile"),
                                   "trajectory": _strata(records, "trajectory_category")},
        "future_forecast_interval": future, "retained_legacy_rmse": dict(retained_legacy_rmse),
        "operational_scenario_relationship": {"forecast_empirical_range_role": "uncertainty_evidence_only",
            "preparedness_scenario_role": "legacy_rf_rmse_planning_sensitivity",
            "empirical_range_drives_operational_directives": False},
        "is_prediction_interval": False, "calibrated_on_synthetic_data": True, "limitations": limitations,
        "deployment_id": profile["deployment_id"], "deployment_gate": profile["deployment_gate"],
        "data_mode": profile["data_mode"], "formula_registry_version": profile["formula_registry_version"],
        "formula_registry_sha256": profile["formula_registry_sha256"], "deployment_profile_sha256": provenance["deployment_profile_sha256"],
        "evidence_registry_sha256": provenance["evidence_registry_sha256"], "provenance": dict(provenance),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return artifact


def validate_uncertainty_artifact(value: Mapping[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(value)
    if value.get("method_id") != METHOD_ID or value.get("is_prediction_interval") is not False:
        raise ValueError("P1.3 uncertainty method or interval status is invalid.")
    records = value["historical_evaluation"]["records"]
    if len(records) != 48 or any(row["prior_residual_count"] != WARMUP_FOLDS+i for i, row in enumerate(records)):
        raise ValueError("Prequential predecessor-only evaluation invariant failed.")
    if MANDATORY_MEANING not in value.get("limitations", []):
        raise ValueError("Mandatory P1.3 limitation is missing.")


def validate_committed_bundle(forecast: Mapping[str, Any], uncertainty: Mapping[str, Any], card: Mapping[str, Any],
                              uncertainty_bytes: bytes, forecast_bytes: bytes) -> None:
    validate_uncertainty_artifact(uncertainty)
    digest = _sha(uncertainty_bytes)
    compact = forecast.get("forecast_uncertainty", {})
    if compact.get("uncertainty_artifact_sha256") != digest or card.get("uncertainty_artifact_sha256") != digest:
        raise ValueError("Uncertainty artifact hash differs from forecast/model-card commit record.")
    if card.get("forecast_artifact_sha256") != _sha(forecast_bytes):
        raise ValueError("Forecast artifact hash differs from model-card commit record.")
    if forecast.get("preparedness_scenarios") is None:
        raise ValueError("Authoritative preparedness scenarios are missing.")
    if forecast.get("uncertainty_scenarios") != forecast.get("preparedness_scenarios"):
        raise ValueError("Deprecated scenario alias differs from authoritative preparedness scenarios.")
    if compact.get("is_prediction_interval") is not False or compact.get("active_model_id") != ACTIVE_MODEL_ID:
        raise ValueError("Compact forecast uncertainty binding is invalid.")


def main() -> None:
    uncertainty_bytes = UNCERTAINTY_PATH.read_bytes(); forecast_bytes = FORECAST_PATH.read_bytes()
    uncertainty = json.loads(uncertainty_bytes); forecast = json.loads(forecast_bytes)
    card = json.loads(MODEL_CARD_PATH.read_text(encoding="utf-8"))
    validate_committed_bundle(forecast, uncertainty, card, uncertainty_bytes, forecast_bytes)
    print("P1.3 temporally evaluated synthetic empirical range bundle validated.")


if __name__ == "__main__":
    main()
