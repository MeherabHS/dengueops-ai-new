"""Shared, side-effect-free empirical-range mathematics and runtime RF calibration."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from feature_engineering import FEATURE_COLUMNS
from model_factory import build_candidate_estimator, canonical_sha256


METHOD_ID = "prequential_expanding_absolute_residual_quantile"
METHOD_VERSION = "p1.3-v1"
NOMINAL_COVERAGE = 0.90
WARMUP_FOLDS = 20
REQUIRED_RESIDUALS = 68
INITIAL_TRAINING_ROWS = 104
EMBARGO_ROWS = 1
FOLD_STEP_ROWS = 1
TARGET_COLUMN = "target_cases_next_2w"
HORIZON_WEEKS = 2


def finite_sample_quantile(
    values: Sequence[float], nominal_coverage: float = NOMINAL_COVERAGE,
) -> tuple[int, float]:
    if not values or not 0 < nominal_coverage < 1:
        raise ValueError("A nonempty residual pool and valid nominal coverage are required.")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise ValueError("Calibration scores must be finite and nonnegative.")
    n = len(ordered)
    rank = min(n, math.ceil((n + 1) * nominal_coverage))
    return rank, ordered[rank - 1]


def construct_raw_interval(point_raw: float, quantile: float) -> dict[str, Any]:
    if not math.isfinite(point_raw) or not math.isfinite(quantile) or quantile < 0:
        raise ValueError("Point prediction and quantile must be finite; quantile must be nonnegative.")
    lower_unclipped = point_raw - quantile
    lower = max(0.0, lower_unclipped)
    upper = point_raw + quantile
    if lower > upper or not lower <= point_raw <= upper:
        raise ValueError("Empirical range invariant failed.")
    return {
        "lower_raw_unclipped": lower_unclipped,
        "lower_raw": lower,
        "upper_raw": upper,
        "lower_clipping_applied": lower != lower_unclipped,
    }


def _mean(values: Sequence[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def aggregate_prequential_records(
    records: Sequence[Mapping[str, Any]], *, nominal_coverage: float = NOMINAL_COVERAGE,
    warmup_folds: int = WARMUP_FOLDS, residual_count: int = REQUIRED_RESIDUALS,
) -> dict[str, Any]:
    if not records:
        raise ValueError("Historical empirical coverage requires evaluated folds.")
    widths = [float(row["upper_raw"]) - float(row["lower_raw"]) for row in records]
    lower_misses = [float(row["miss_magnitude"]) for row in records if row["miss_direction"] == "lower"]
    upper_misses = [float(row["miss_magnitude"]) for row in records if row["miss_direction"] == "upper"]
    covered = sum(bool(row["covered"]) for row in records)
    return {
        "nominal_coverage": nominal_coverage,
        "observed_coverage": covered / len(records),
        "coverage_gap": covered / len(records) - nominal_coverage,
        "covered_fold_count": covered,
        "evaluated_fold_count": len(records),
        "calibration_warmup_fold_count": warmup_folds,
        "average_interval_width": _mean(widths),
        "median_interval_width": float(statistics.median(widths)),
        "minimum_interval_width": min(widths),
        "maximum_interval_width": max(widths),
        "lower_miss_count": len(lower_misses),
        "upper_miss_count": len(upper_misses),
        "mean_lower_miss_magnitude": _mean(lower_misses),
        "mean_upper_miss_magnitude": _mean(upper_misses),
        "residual_count": residual_count,
        "first_evaluated_fold_id": records[0]["fold_id"],
        "last_evaluated_fold_id": records[-1]["fold_id"],
    }


def build_prequential_evaluation(
    residuals: Sequence[Mapping[str, Any]], *, expected_folds: int = REQUIRED_RESIDUALS,
    warmup_folds: int = WARMUP_FOLDS, nominal_coverage: float = NOMINAL_COVERAGE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(residuals) != expected_folds:
        raise ValueError(f"Prequential evaluation requires exactly {expected_folds} ordered residuals.")
    if warmup_folds <= 0 or warmup_folds >= expected_folds:
        raise ValueError("Calibration warm-up must leave at least one evaluation fold.")
    records: list[dict[str, Any]] = []
    for index in range(warmup_folds, expected_folds):
        predecessors = [float(row["absolute_residual"]) for row in residuals[:index]]
        if len(predecessors) != index:
            raise ValueError("Evaluation fold does not use exactly its predecessor residuals.")
        rank, quantile = finite_sample_quantile(predecessors, nominal_coverage)
        current = residuals[index]
        bounds = construct_raw_interval(float(current["raw_prediction"]), quantile)
        actual = float(current["actual"])
        covered = bounds["lower_raw"] <= actual <= bounds["upper_raw"]
        direction = None
        magnitude = 0.0
        if actual < bounds["lower_raw"]:
            direction = "lower"
            magnitude = bounds["lower_raw"] - actual
        elif actual > bounds["upper_raw"]:
            direction = "upper"
            magnitude = actual - bounds["upper_raw"]
        records.append({
            "fold_id": current["fold_id"], "target_period": current["target_period"],
            "actual": actual, "raw_prediction": current["raw_prediction"],
            "prior_residual_count": index, "quantile_rank": rank,
            "quantile_value": quantile, **bounds, "covered": covered,
            "miss_direction": direction, "miss_magnitude": magnitude,
            "case_quartile": current.get("case_quartile"),
            "trajectory_category": current.get("trajectory_category"),
        })
    return records, aggregate_prequential_records(
        records, nominal_coverage=nominal_coverage, warmup_folds=warmup_folds,
        residual_count=expected_folds,
    )


def advance_iso_period(year: int, week: int, weeks: int) -> tuple[int, int]:
    try:
        monday = date.fromisocalendar(int(year), int(week), 1) + timedelta(weeks=int(weeks))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid ISO epidemiological forecast origin.") from exc
    target_year, target_week, _ = monday.isocalendar()
    if target_week == 53:
        raise ValueError("The governed runtime period contract does not support ISO week 53 targets.")
    return target_year, target_week


def _period(row: Mapping[str, Any] | pd.Series) -> str:
    return f"{int(row['epi_year'])}-W{int(row['epi_week']):02d}"


def matrix_sha256(frame: pd.DataFrame, feature_order: Sequence[str], target_column: str) -> str:
    rows = [{
        "epi_year": int(row["epi_year"]), "epi_week": int(row["epi_week"]),
        "features": [float(row[name]) for name in feature_order],
        "target": float(row[target_column]),
    } for _, row in frame.iterrows()]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_runtime_fold_plan(
    frame: pd.DataFrame, *, feature_order: Sequence[str] = FEATURE_COLUMNS,
    target_column: str = TARGET_COLUMN,
) -> tuple[list[dict[str, Any]], str]:
    expected_features = list(FEATURE_COLUMNS)
    supplied_features = list(feature_order)
    frame_feature_order = [name for name in frame.columns if name in set(expected_features)]
    if supplied_features != expected_features or frame_feature_order != expected_features:
        raise ValueError("Runtime calibration feature order differs from the canonical 18-feature contract.")
    required = ["epi_year", "epi_week", "cases", *expected_features, target_column]
    if any(name not in frame.columns for name in required):
        raise ValueError("Runtime calibration matrix is missing required columns.")
    ordered = frame.reset_index(drop=True)
    if ordered[["epi_year", "epi_week"]].duplicated().any():
        raise ValueError("Runtime calibration periods contain duplicates.")
    periods = [(int(row.epi_year), int(row.epi_week)) for row in ordered.itertuples()]
    if periods != sorted(periods):
        raise ValueError("Runtime calibration periods are not chronological.")
    mondays: list[date] = []
    for year, week in periods:
        if week == 53:
            raise ValueError("The governed runtime period contract does not support ISO week 53 rows.")
        try:
            mondays.append(date.fromisocalendar(year, week, 1))
        except ValueError as exc:
            raise ValueError("Runtime calibration contains an invalid ISO period.") from exc
    if any(right - left != timedelta(weeks=1) for left, right in zip(mondays, mondays[1:])):
        raise ValueError("Runtime calibration periods are not contiguous ISO weeks.")
    values = ordered[expected_features + [target_column]].to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError("Runtime calibration matrix contains non-finite features or targets.")
    if (ordered[target_column].to_numpy(float) < 0).any():
        raise ValueError("Runtime calibration targets must be nonnegative.")

    first_validation = INITIAL_TRAINING_ROWS + EMBARGO_ROWS
    available_folds = len(range(first_validation, len(ordered), FOLD_STEP_ROWS))
    if available_folds != REQUIRED_RESIDUALS:
        empty_hash = canonical_sha256([])
        return [], empty_hash

    plan: list[dict[str, Any]] = []
    for sequence, validation_index in enumerate(range(first_validation, len(ordered), FOLD_STEP_ROWS), 1):
        train_end_exclusive = validation_index - EMBARGO_ROWS
        embargo_index = train_end_exclusive
        if train_end_exclusive < INITIAL_TRAINING_ROWS or embargo_index >= validation_index:
            raise ValueError("Runtime calibration fold boundaries are invalid.")
        train = ordered.iloc[:train_end_exclusive]
        validation = ordered.iloc[validation_index]
        origin_year, origin_week = int(validation["epi_year"]), int(validation["epi_week"])
        target_year, target_week = advance_iso_period(origin_year, origin_week, HORIZON_WEEKS)
        latest_label_year, latest_label_week = advance_iso_period(
            int(train.iloc[-1]["epi_year"]), int(train.iloc[-1]["epi_week"]), HORIZON_WEEKS,
        )
        if (latest_label_year, latest_label_week) > (origin_year, origin_week):
            raise ValueError("Runtime calibration training includes a target unavailable at the forecast origin.")
        fold_id = f"rolling-origin-{sequence:04d}-{origin_year}-W{origin_week:02d}-to-{target_year}-W{target_week:02d}"
        plan.append({
            "foldId": fold_id, "foldSequence": sequence, "originPeriod": f"{origin_year}-W{origin_week:02d}",
            "targetPeriod": f"{target_year}-W{target_week:02d}", "trainingRowCount": len(train),
            "trainingMatrixSha256": matrix_sha256(train, expected_features, target_column),
            "validationMatrixSha256": matrix_sha256(validation.to_frame().T, expected_features, target_column),
            "actualTarget": float(validation[target_column]), "trainEndExclusive": train_end_exclusive,
            "embargoIndex": embargo_index, "validationIndex": validation_index,
        })
    public_plan = [{key: value for key, value in fold.items() if key not in {"trainEndExclusive", "embargoIndex", "validationIndex"}} for fold in plan]
    return plan, canonical_sha256(public_plan)


def generate_runtime_rf_residuals(
    frame: pd.DataFrame, registry: Mapping[str, Any], *, registry_sha256: str,
    expected_registry_sha256: str, expected_parameters_sha256: str,
    feature_order: Sequence[str] = FEATURE_COLUMNS, target_column: str = TARGET_COLUMN,
) -> dict[str, Any]:
    if registry_sha256 != expected_registry_sha256:
        raise ValueError("Runtime calibration candidate-registry identity changed.")
    candidate = next((item for item in registry.get("candidates", []) if item.get("model_id") == "random_forest"), None)
    if candidate is None or candidate.get("parameters_sha256") != expected_parameters_sha256:
        raise ValueError("Runtime calibration Random Forest parameter identity changed.")
    plan, plan_hash = build_runtime_fold_plan(frame, feature_order=feature_order, target_column=target_column)
    if not plan:
        return {"status": "pending_dataset_specific_calibration", "foldPlanSha256": plan_hash, "folds": [], "residuals": []}

    folds: list[dict[str, Any]] = []
    residuals: list[dict[str, Any]] = []
    for descriptor in plan:
        train = frame.iloc[:descriptor["trainEndExclusive"]]
        validation = frame.iloc[descriptor["validationIndex"]]
        estimator = build_candidate_estimator("random_forest", dict(registry))
        estimator.fit(train[list(feature_order)].to_numpy(float), train[target_column].to_numpy(float))
        raw = float(estimator.predict(validation[list(feature_order)].to_numpy(float).reshape(1, -1))[0])
        actual = float(descriptor["actualTarget"])
        signed = actual - raw
        absolute = abs(signed)
        if not all(math.isfinite(value) for value in (actual, raw, signed, absolute)) or raw < 0:
            raise ValueError("Runtime calibration produced a non-finite or invalid Random Forest residual.")
        fold = {key: value for key, value in descriptor.items() if key not in {"trainEndExclusive", "embargoIndex", "validationIndex"}}
        fold.update(rawPrediction=raw, signedResidual=signed, absoluteResidual=absolute)
        folds.append(fold)
        residuals.append({
            "fold_id": descriptor["foldId"], "target_period": descriptor["targetPeriod"],
            "actual": actual, "raw_prediction": raw, "residual": signed,
            "absolute_residual": absolute,
        })
    if len(folds) != REQUIRED_RESIDUALS:
        raise ValueError("Runtime calibration did not produce exactly 68 complete residual folds.")
    return {"status": "available", "foldPlanSha256": plan_hash, "folds": folds, "residuals": residuals}
