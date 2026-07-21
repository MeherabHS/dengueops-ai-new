"""
validation_backtest.py
======================
DengueOps AI — Phase 3: Temporal Backtesting and Baseline Comparison

Evaluates three forecasting approaches on a strictly chronological holdout set:
    1. Naive (Last Known)        — predict using cases_lag_1w from the feature row
    2. Moving Average            — predict using cases_rolling_4w from the feature row
    3. GradientBoostingRegressor — trained on FEATURE_COLUMNS from feature_engineering.py

Outputs:
    data/validation_metrics.json

Why time-based validation?
    Random train/test splits are inappropriate for time series data. If training
    data includes future observations (e.g., 2026 week 12 in train, 2025 week 40
    in test), the model can memorise future patterns and produce unrealistically
    strong test metrics that collapse when deployed on genuinely unseen future data.

    A strict chronological holdout — using the first 80% of rows for training and
    the remaining 20% for testing — guarantees that every test prediction is made
    using only information that would have been available at that point in time.
    This mimics real operational deployment conditions.

Usage:
    python analytics/validation_backtest.py
"""

from __future__ import annotations

import json
import math
import sys
import hashlib
import os
import tempfile
from datetime import datetime, timezone, date, timedelta
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from formula_registry import build_formula_metadata, current_deployment_gate

# ── Path setup: allow importing from the analytics/ sibling directory ─────────
sys.path.insert(0, str(Path(__file__).parent))
from feature_engineering import (
    build_features,
    FEATURE_COLUMNS,
    DEFAULT_OUTPUT_PATH as FEATURES_CSV,
)
from provenance import PROVENANCE_COLUMNS, derive_data_mode, provenance_from_feature_frame
from deployment_profiles import load_deployment_profile
from evidence_registry import evidence_registry_sha256
from explainability_engine import feature_formula_id, feature_order_sha256, model_parameters_sha256
from jsonschema import Draft202012Validator
from explainability_engine import (
    DEFAULT_OUTPUT_PATH as EXPLAINABILITY_OUTPUT,
    build_model_explainability,
    write_explainability_atomic,
)
from model_factory import build_candidate_estimator, load_and_validate_candidate_registry

# ── Output path ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
VALIDATION_OUTPUT = ROOT / "data" / "validation_metrics.json"
ROLLING_VALIDATION_OUTPUT = ROOT / "data" / "rolling_validation.json"
ROLLING_SCHEMA_PATH = ROOT / "config" / "rolling_validation.schema.json"

# ── Backtest configuration ─────────────────────────────────────────────────────
TRAIN_FRACTION = 0.80        # 80% train / 20% test chronological split
TARGET_COL = "target_cases_next_2w"   # 14-day ahead forecast target
RANDOM_STATE = 42

# GBR hyperparameters
_CANDIDATE_REGISTRY, _ = load_and_validate_candidate_registry(ROOT / "config" / "candidate_models_p1.2a-v1.json")
GBR_PARAMS: dict = dict(next(candidate for candidate in _CANDIDATE_REGISTRY["candidates"]
                             if candidate["model_id"] == "gradient_boosting")["parameters"])

VALIDATION_FORMULA_IDS = (
    "TARGET.HORIZON.2W", "FEATURE.CASE_LAGS", "FEATURE.CLIMATE_LAGS",
    "FEATURE.CASE_ROLLING", "FEATURE.GROWTH_RATIOS", "FEATURE.SEASONAL_CYCLIC",
    "FEATURE.SEASON_FLAGS", "MODEL.GBR.CONFIG", "MODEL.BASELINE.NAIVE",
    "MODEL.BASELINE.MA4", "METRIC.MAE", "METRIC.RMSE", "METRIC.MAPE",
)


@dataclass(frozen=True)
class BacktestContext:
    result: dict
    validation_model: Any
    train_df: pd.DataFrame
    test_df: pd.DataFrame
    X_test: np.ndarray
    y_test: np.ndarray
    feature_names: tuple[str, ...]
    target: str
    model_parameters: dict
    provenance: dict | None


# ─────────────────────────────────────────────────────────────────────────────
# Metric utilities
# ─────────────────────────────────────────────────────────────────────────────

def compute_mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Mean Absolute Error."""
    return float(np.mean(np.abs(actual - predicted)))


def compute_rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Root Mean Squared Error."""
    return float(math.sqrt(np.mean((actual - predicted) ** 2)))


def compute_mape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Mean Absolute Percentage Error, computed only on rows where actual > 0.
    Returns NaN if no valid rows remain.
    """
    mask = actual > 0
    if not mask.any():
        return float("nan")
    return float(np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100)


def compute_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict:
    """Compute MAE, RMSE, MAPE and return as a dict with values rounded to 2 dp."""
    return {
        "mae": round(compute_mae(actual, predicted), 2),
        "rmse": round(compute_rmse(actual, predicted), 2),
        "mape": round(compute_mape(actual, predicted), 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Load / build feature matrix
# ─────────────────────────────────────────────────────────────────────────────

def load_feature_matrix() -> pd.DataFrame:
    """
    Load model_features.csv if it exists, otherwise build it on the fly.
    The returned DataFrame is guaranteed to be sorted by (epi_year, epi_week).
    """
    if Path(FEATURES_CSV).exists():
        df = pd.read_csv(FEATURES_CSV)
        df = df.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
        return df

    print("  model_features.csv not found — building features now...")
    df, _ = build_features()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Baseline predictions
# ─────────────────────────────────────────────────────────────────────────────

def predict_naive(test_df: pd.DataFrame) -> np.ndarray:
    """
    Naive forecast: predict the target using the most recent known case count
    (cases_lag_1w), which represents last week's observed cases.

    Rationale: this baseline tests whether any model adds value over simply
    assuming the current trajectory continues. If the ML model cannot beat
    this baseline, it provides no useful signal.
    """
    return test_df["cases_lag_1w"].values.astype(float)


def predict_moving_average(test_df: pd.DataFrame) -> np.ndarray:
    """
    Moving average forecast: predict using the 4-week rolling mean of past cases.

    This baseline smooths out week-to-week noise and represents the most recent
    short-term trend. It is harder to beat than the naive baseline during stable
    or slowly trending periods.
    """
    return test_df["cases_rolling_4w"].values.astype(float)


# ─────────────────────────────────────────────────────────────────────────────
# Backtest runner
# ─────────────────────────────────────────────────────────────────────────────

def _run_backtest_context(df: pd.DataFrame) -> BacktestContext:
    """
    Run temporal backtest with naive, moving average, and GBR models.

    Split strategy:
        - Data is already sorted by (epi_year, epi_week).
        - Rows 0 to train_cutoff-1 are used for training.
        - Rows train_cutoff to end are used for testing.
        - No shuffling occurs at any step. This preserves temporal ordering.

    Parameters
    ----------
    df : pd.DataFrame
        Feature matrix from build_features(), sorted chronologically.

    Returns
    -------
    dict
        Backtest results including metrics per model and actual_vs_predicted rows.
    """
    n_rows = len(df)
    train_cutoff = int(n_rows * TRAIN_FRACTION)   # e.g. int(121 * 0.80) = 96
    test_start = train_cutoff

    train_df = df.iloc[:train_cutoff].copy()
    test_df = df.iloc[test_start:].copy()

    # ── Feature matrix and targets ────────────────────────────────────────────
    X_train = train_df[FEATURE_COLUMNS].values
    y_train = train_df[TARGET_COL].values

    X_test = test_df[FEATURE_COLUMNS].values
    y_test = test_df[TARGET_COL].values

    # ── Train GBR ─────────────────────────────────────────────────────────────
    # random_state is fixed for full reproducibility. n_estimators and
    # learning_rate are conservative to avoid overfitting on a small dataset.
    gbr = build_candidate_estimator("gradient_boosting", _CANDIDATE_REGISTRY)
    gbr.fit(X_train, y_train)
    y_pred_gbr = np.maximum(0, gbr.predict(X_test))   # clamp negative predictions

    # ── Baselines ─────────────────────────────────────────────────────────────
    y_pred_naive = predict_naive(test_df)
    y_pred_ma = predict_moving_average(test_df)

    # ── Metrics ───────────────────────────────────────────────────────────────
    metrics = {
        "naive": compute_metrics(y_test, y_pred_naive),
        "moving_average": compute_metrics(y_test, y_pred_ma),
        "gradient_boosting": compute_metrics(y_test, y_pred_gbr),
    }

    # ── Determine best model by MAE ───────────────────────────────────────────
    best_model = min(metrics, key=lambda k: metrics[k]["mae"])

    # ── Actual vs predicted table ─────────────────────────────────────────────
    actual_vs_predicted = []
    for i, (_, row) in enumerate(test_df.iterrows()):
        actual_vs_predicted.append({
            "epi_year": int(row["epi_year"]),
            "epi_week": int(row["epi_week"]),
            "actual": int(round(y_test[i])),
            "naive_pred": int(round(y_pred_naive[i])),
            "moving_average_pred": int(round(y_pred_ma[i])),
            "ml_pred": int(round(y_pred_gbr[i])),
        })

    provenance = provenance_from_feature_frame(df) if set(PROVENANCE_COLUMNS).issubset(df.columns) else None
    data_mode = derive_data_mode(provenance) if provenance else "synthetic"
    source_note = {
        "synthetic": "Results use synthetic case, climate, and operational inputs.",
        "real": "Results use non-synthetic inputs recorded in the input manifest.",
        "mixed": "Results use a manifest-recorded mixture of synthetic and non-synthetic inputs.",
    }[data_mode]
    result = {
        "target": TARGET_COL,
        "validation_design": "time_based_holdout_final_20_percent",
        "train_rows": int(train_cutoff),
        "test_rows": int(n_rows - train_cutoff),
        "train_period": {
            "epi_year_start": int(df.iloc[0]["epi_year"]),
            "epi_week_start": int(df.iloc[0]["epi_week"]),
            "epi_year_end": int(df.iloc[train_cutoff - 1]["epi_year"]),
            "epi_week_end": int(df.iloc[train_cutoff - 1]["epi_week"]),
        },
        "test_period": {
            "epi_year_start": int(df.iloc[test_start]["epi_year"]),
            "epi_week_start": int(df.iloc[test_start]["epi_week"]),
            "epi_year_end": int(df.iloc[-1]["epi_year"]),
            "epi_week_end": int(df.iloc[-1]["epi_week"]),
        },
        "metrics": metrics,
        "best_model": best_model,
        "gbr_params": GBR_PARAMS,
        "feature_count": len(FEATURE_COLUMNS),
        "features_used": FEATURE_COLUMNS,
        "actual_vs_predicted": actual_vs_predicted,
        "notes": [
            "Validation uses final chronological 20% of available feature rows.",
            "Time-based holdout only — no random shuffling at any step.",
            source_note,
            "This validates pipeline behaviour and feature engineering correctness, "
            "not deployment-grade epidemiological accuracy.",
            "Real validation would require multi-year validated DGHS/IEDCR surveillance data.",
        ],
    }
    if provenance is not None:
        result["provenance"] = provenance
        result["data_mode"] = data_mode
    result.update(build_formula_metadata(VALIDATION_FORMULA_IDS, current_deployment_gate()))
    return BacktestContext(
        result=result,
        validation_model=gbr,
        train_df=train_df,
        test_df=test_df,
        X_test=X_test,
        y_test=y_test,
        feature_names=tuple(FEATURE_COLUMNS),
        target=TARGET_COL,
        model_parameters=dict(GBR_PARAMS),
        provenance=provenance,
    )


def run_backtest(df: pd.DataFrame) -> dict:
    """Preserve the public result-only backtest contract."""
    return _run_backtest_context(df).result


INITIAL_TRAINING_WINDOW = 104
HORIZON_WEEKS = 2
STEP_WEEKS = 1
LABEL_AVAILABILITY_POLICY = "target_label_available_when_target_period_is_at_or_before_forecast_origin"
ROLLING_FORMULA_IDS = (*VALIDATION_FORMULA_IDS, "VALIDATION.ROLLING_ORIGIN")
MODEL_NAMES = ("gradient_boosting", "naive", "moving_average")


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _period(row: pd.Series) -> str:
    return f"{int(row['epi_year'])}-W{int(row['epi_week']):02d}"


def _advance_period(row: pd.Series, weeks: int) -> str:
    monday = date.fromisocalendar(int(row["epi_year"]), int(row["epi_week"]), 1) + timedelta(weeks=weeks)
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


def _matrix_sha(frame: pd.DataFrame) -> str:
    rows = []
    for _, row in frame.iterrows():
        rows.append({
            "epi_year": int(row["epi_year"]), "epi_week": int(row["epi_week"]),
            "features": [float(row[name]) for name in FEATURE_COLUMNS],
            "target": float(row[TARGET_COL]),
        })
    return _canonical_sha(rows)


def generate_rolling_fold_descriptors(df: pd.DataFrame) -> tuple[dict, ...]:
    """Return the immutable authoritative P1.1 fold definitions."""
    ordered = df.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    if len(ordered) != 173 or ordered[["epi_year", "epi_week"]].duplicated().any():
        raise ValueError("Expected 173 sorted unique labeled rows.")
    if any(int(value) == 53 for value in ordered["epi_week"]):
        raise ValueError("W53 is not supported by the current benchmark.")
    descriptors = []
    for fold_index, validation_index in enumerate(range(INITIAL_TRAINING_WINDOW + 1, len(ordered)), 1):
        train_end_exclusive = validation_index - 1
        train = ordered.iloc[:train_end_exclusive]
        embargo = ordered.iloc[validation_index - 1]
        validation_row = ordered.iloc[validation_index]
        origin = _period(validation_row)
        target_period = _advance_period(validation_row, HORIZON_WEEKS)
        descriptors.append({
            "fold_id": f"rolling-origin-{fold_index:04d}-{origin}-to-{target_period}",
            "fold_index": fold_index,
            "train_start_index": 0,
            "train_end_exclusive": train_end_exclusive,
            "embargo_index": validation_index - 1,
            "validation_index": validation_index,
            "training_matrix_sha256": _matrix_sha(train),
            "validation_matrix_sha256": _matrix_sha(validation_row.to_frame().T),
            "origin_period": origin,
            "target_period": target_period,
            "feature_order_sha256": feature_order_sha256(FEATURE_COLUMNS),
            "actual_target": float(validation_row[TARGET_COL]),
            "label_availability_policy": LABEL_AVAILABILITY_POLICY,
        })
    return tuple(descriptors)


def _published_prediction(raw: float) -> tuple[float, bool]:
    if not math.isfinite(raw):
        raise ValueError("A rolling-origin model produced a non-finite prediction.")
    return max(0.0, raw), raw < 0.0


def _error_record(raw: float, actual: float) -> dict:
    prediction, clipped = _published_prediction(raw)
    signed = prediction - actual
    return {
        "raw_prediction": raw, "published_prediction": prediction, "prediction": prediction,
        "clipping_applied": clipped, "actual": actual, "signed_error": signed,
        "absolute_error": abs(signed), "squared_error": signed * signed,
        "percentage_error": abs(signed) / actual * 100 if actual > 0 else None,
        "percentage_error_exclusion_reason": None if actual > 0 else "actual_is_zero",
        "error_direction": "under_prediction" if signed < 0 else "over_prediction" if signed > 0 else "exact",
    }


def aggregate_error_records(records: list[dict]) -> dict:
    absolute = np.asarray([r["absolute_error"] for r in records], dtype=float)
    squared = np.asarray([r["squared_error"] for r in records], dtype=float)
    percentages = [r["percentage_error"] for r in records if r["percentage_error"] is not None]
    actual_total = float(sum(r["actual"] for r in records))
    q1, q3 = np.percentile(absolute, [25, 75])
    return {
        "fold_count": len(records), "mae": float(absolute.mean()), "rmse": float(np.sqrt(squared.mean())),
        "mape": float(np.mean(percentages)) if percentages else None,
        "mape_included_row_count": len(percentages), "mape_zero_actual_exclusion_count": len(records) - len(percentages),
        "wape": float(100 * absolute.sum() / actual_total) if actual_total else None,
        "wape_exclusion_reason": None if actual_total else "total_actual_is_zero",
        "median_absolute_error": float(np.median(absolute)),
        "absolute_error_standard_deviation": float(np.std(absolute, ddof=0)),
        "minimum_absolute_error": float(absolute.min()), "maximum_absolute_error": float(absolute.max()),
        "q1_absolute_error": float(q1), "q3_absolute_error": float(q3), "iqr_absolute_error": float(q3 - q1),
    }


def _comparison(folds: list[dict], metrics: dict) -> list[dict]:
    result = []
    for model in MODEL_NAMES:
        wins = ties = losses = 0
        for fold in folds:
            own = fold["predictions"][model]["absolute_error"]
            others = [fold["predictions"][key]["absolute_error"] for key in MODEL_NAMES if key != model]
            best_other = min(others)
            if abs(own - best_other) <= 1e-9: ties += 1
            elif own < best_other: wins += 1
            else: losses += 1
        def improve(baseline: str):
            value = metrics[baseline]["mae"]
            return None if value == 0 else 100 * (value - metrics[model]["mae"]) / value
        result.append({"model_name": model, "fold_count": len(folds), "mae": metrics[model]["mae"],
            "rmse": metrics[model]["rmse"], "wape": metrics[model]["wape"],
            "median_absolute_error": metrics[model]["median_absolute_error"],
            "improvement_vs_naive_percent": improve("naive"),
            "improvement_vs_moving_average_percent": improve("moving_average"),
            "wins": wins, "ties": ties, "losses": losses})
    return result


def _group_summary(folds: list[dict], key) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for fold in folds: groups.setdefault(str(key(fold)), []).append(fold)
    output = []
    for name, items in groups.items():
        errors = np.asarray([item["predictions"]["gradient_boosting"]["absolute_error"] for item in items])
        q1, q3 = np.percentile(errors, [25, 75]); best = int(np.argmin(errors)); worst = int(np.argmax(errors))
        output.append({"group": name, "row_count": len(items), "mae": float(errors.mean()),
            "median_absolute_error": float(np.median(errors)), "standard_deviation": float(np.std(errors, ddof=0)),
            "q1": float(q1), "q3": float(q3), "iqr": float(q3-q1),
            "best_fold_id": items[best]["fold_id"], "worst_fold_id": items[worst]["fold_id"]})
    return output


def _native_stability(native_values: list[np.ndarray]) -> dict:
    matrix = np.asarray(native_values, dtype=float)
    ranks = np.empty_like(matrix)
    for row_index, row in enumerate(matrix):
        order = sorted(range(len(row)), key=lambda i: (-row[i], i))
        for rank, feature_index in enumerate(order, 1): ranks[row_index, feature_index] = rank
    features = []
    for i, name in enumerate(FEATURE_COLUMNS):
        values = matrix[:, i]; rank_values = ranks[:, i]; q1, q3 = np.percentile(values, [25, 75])
        features.append({"feature_name": name, "feature_index": i, "mean_native_importance": float(values.mean()),
            "median_native_importance": float(np.median(values)), "standard_deviation": float(np.std(values, ddof=0)),
            "q1": float(q1), "q3": float(q3), "iqr": float(q3-q1), "mean_rank": float(rank_values.mean()),
            "rank_standard_deviation": float(np.std(rank_values, ddof=0)),
            "top_5_frequency": float(np.mean(rank_values <= 5)), "zero_importance_frequency": float(np.mean(values == 0)),
            "folds_evaluated": len(matrix)})
    return {"method": "native_tree_importance_across_rolling_folds", "folds_evaluated": len(matrix), "features": features}


def validate_rolling_validation(artifact: dict, *, expected_df: pd.DataFrame | None = None,
                                expected_provenance: dict | None = None, expected_model_card: dict | None = None,
                                expected_artifact_sha256: str | None = None) -> None:
    schema = json.loads(ROLLING_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = [e.message for e in Draft202012Validator(schema).iter_errors(artifact)]
    if artifact.get("fold_count") != 68 or len(artifact.get("folds", [])) != 68: errors.append("Rolling fold count must be 68.")
    if artifact.get("feature_names") != list(FEATURE_COLUMNS): errors.append("Rolling feature order mismatch.")
    if artifact.get("target") != TARGET_COL: errors.append("Rolling target mismatch.")
    if artifact.get("horizon_weeks") != 2: errors.append("Rolling horizon mismatch.")
    provenance = artifact.get("provenance", {})
    if artifact.get("formula_registry_version") != provenance.get("formula_registry_version"):
        errors.append("Rolling formula-registry version differs from provenance.")
    if artifact.get("formula_registry_sha256") != provenance.get("formula_registry_sha256"):
        errors.append("Rolling formula-registry hash differs from provenance.")
    if expected_df is not None:
        expected = build_rolling_validation(expected_df, validate=False)
        for key in ("feature_order_sha256", "model_parameters_sha256"):
            if artifact.get(key) != expected.get(key): errors.append(f"Rolling {key} mismatch.")
        if [f.get("training_matrix_sha256") for f in artifact.get("folds", [])] != [f["training_matrix_sha256"] for f in expected["folds"]]:
            errors.append("Rolling training matrices are stale or altered.")
    if expected_provenance is not None:
        if artifact.get("provenance") != expected_provenance: errors.append("Rolling provenance mismatch.")
        if artifact.get("formula_registry_version") != expected_provenance.get("formula_registry_version"): errors.append("Rolling current formula-registry version mismatch.")
        if artifact.get("formula_registry_sha256") != expected_provenance.get("formula_registry_sha256"): errors.append("Rolling current formula-registry hash mismatch.")
    if expected_model_card is not None and expected_artifact_sha256 != expected_model_card.get("rolling_validation_artifact_sha256"):
        errors.append("Model-card rolling artifact hash mismatch.")
    if errors: raise ValueError(" ".join(errors))


def build_rolling_validation(df: pd.DataFrame, *, validate: bool = True) -> dict:
    df = df.sort_values(["epi_year", "epi_week"]).reset_index(drop=True)
    if len(df) != 173 or df[["epi_year", "epi_week"]].duplicated().any(): raise ValueError("Expected 173 sorted unique labeled rows.")
    if any(int(v) == 53 for v in df["epi_week"]): raise ValueError("W53 is not supported by the current benchmark.")
    if len(FEATURE_COLUMNS) != 18 or not np.isfinite(df[FEATURE_COLUMNS].to_numpy(float)).all(): raise ValueError("Canonical feature matrix is invalid.")
    folds, native_values = [], []
    for descriptor in generate_rolling_fold_descriptors(df):
        fold_index = descriptor["fold_index"]
        train = df.iloc[descriptor["train_start_index"]:descriptor["train_end_exclusive"]]
        embargo = df.iloc[descriptor["embargo_index"]]
        validation_row = df.iloc[descriptor["validation_index"]]
        model = build_candidate_estimator("gradient_boosting", _CANDIDATE_REGISTRY).fit(train[FEATURE_COLUMNS].to_numpy(), train[TARGET_COL].to_numpy())
        native = np.asarray(model.feature_importances_, dtype=float)
        if len(native) != 18 or not np.isfinite(native).all() or (native < 0).any() or not (np.isclose(native.sum(), 1.0) or np.all(native == 0)):
            raise ValueError("Invalid native feature importances.")
        native_values.append(native)
        raw = float(model.predict(validation_row[FEATURE_COLUMNS].to_numpy(float).reshape(1, -1))[0])
        actual = descriptor["actual_target"]; origin = descriptor["origin_period"]; target_period = descriptor["target_period"]
        predictions = {"gradient_boosting": _error_record(raw, actual),
                       "naive": _error_record(float(validation_row["cases_lag_1w"]), actual),
                       "moving_average": _error_record(float(validation_row["cases_rolling_4w"]), actual)}
        folds.append({"fold_id": descriptor["fold_id"], "fold_index": fold_index,
            "train_start": _period(train.iloc[0]), "train_end": _period(train.iloc[-1]),
            "latest_training_target_period": _advance_period(train.iloc[-1], 2), "embargo_period": _period(embargo),
            "origin_period": origin, "target_period": target_period, "train_rows": len(train), "validation_rows": 1,
            "horizon_weeks": 2, "step_weeks": 1, "label_availability_policy": LABEL_AVAILABILITY_POLICY,
            "feature_order_sha256": descriptor["feature_order_sha256"], "model_parameters_sha256": model_parameters_sha256(GBR_PARAMS),
            "training_matrix_sha256": descriptor["training_matrix_sha256"], "validation_matrix_sha256": descriptor["validation_matrix_sha256"],
            "data_availability_status": "label_available_at_or_before_origin_with_one_row_embargo",
            "origin_cases": float(validation_row["cases"]), "benchmark_scenario": "normal", "predictions": predictions})
    metric_records = {model: [fold["predictions"][model] for fold in folds] for model in MODEL_NAMES}
    metrics = {model: aggregate_error_records(records) for model, records in metric_records.items()}
    actuals = np.asarray([f["predictions"]["gradient_boosting"]["actual"] for f in folds]); boundaries = np.percentile(actuals, [25, 50, 75])
    for fold in folds:
        target = fold["predictions"]["gradient_boosting"]["actual"]
        fold["target_volume_quartile"] = int(1 + sum(bool(target > b) for b in boundaries))
        fold["trajectory"] = "rising" if target > fold["origin_cases"] else "declining" if target < fold["origin_cases"] else "stable"
    provenance = provenance_from_feature_frame(df) if set(PROVENANCE_COLUMNS).issubset(df.columns) else {}
    profile = load_deployment_profile(provenance["deployment_profile_id"]) if provenance.get("deployment_profile_id") else None
    artifact = {"validation_schema_version": "1.0", "validation_version": "p1.1-v1", "availability_status": "generated",
        "validation_method": "expanding_window_rolling_origin", "primary_validation": True, "initial_training_window": 104,
        "horizon_weeks": 2, "step_weeks": 1, "fold_count": len(folds), "label_availability_policy": LABEL_AVAILABILITY_POLICY,
        "model_id": "gradient_boosting", "model_version": "p1.1-v1",
        "model_parameters": GBR_PARAMS, "model_parameters_sha256": model_parameters_sha256(GBR_PARAMS), "feature_names": list(FEATURE_COLUMNS),
        "feature_formula_ids": sorted(set(feature_formula_id(n) for n in FEATURE_COLUMNS)), "feature_order_sha256": feature_order_sha256(FEATURE_COLUMNS),
        "target": TARGET_COL, "folds": folds, "aggregate_metrics": metrics, "baseline_metrics": {k: metrics[k] for k in ("naive", "moving_average")},
        "model_comparison": _comparison(folds, metrics), "variability_summary": {"overall": _group_summary(folds, lambda _: "overall"),
            "epidemiological_year": _group_summary(folds, lambda f: f["target_period"][:4]),
            "target_volume_quartile": _group_summary(folds, lambda f: f["target_volume_quartile"]),
            "trajectory": _group_summary(folds, lambda f: f["trajectory"]), "benchmark_scenario": _group_summary(folds, lambda f: f["benchmark_scenario"]),
            "target_volume_quartile_boundaries": boundaries.tolist(),
            "target_volume_quartile_bin_counts": [sum(f["target_volume_quartile"] == q for f in folds) for q in range(1, 5)]},
        "period_summary": {"first_origin": folds[0]["origin_period"], "first_target": folds[0]["target_period"],
            "final_origin": folds[-1]["origin_period"], "final_target": folds[-1]["target_period"]},
        "native_importance_stability": _native_stability(native_values), "permutation_stability_status": "not_evaluated_single_row_folds",
        "limitations": ["Rolling-origin validation repeatedly evaluates unseen future periods, but current results are based on deterministic synthetic benchmark data and do not establish real-world Dhaka performance.",
            "Real reporting publication delays and revision vintages are not modeled yet.",
            "Permutation importance was not calculated per fold because each rolling-origin fold contains one validation row, making permutation diagnostics statistically degenerate and unsuitable for temporal-stability claims."],
        "deployment_gate": profile["deployment_gate"] if profile else current_deployment_gate(), "data_mode": profile["data_mode"] if profile else "synthetic_capability_demonstration",
        "observed_data_mode": profile["observed_data_mode"] if profile else "synthetic", **build_formula_metadata(ROLLING_FORMULA_IDS, current_deployment_gate()),
        "deployment_profile_id": provenance.get("deployment_profile_id"), "deployment_profile_sha256": provenance.get("deployment_profile_sha256"),
        "evidence_registry_sha256": provenance.get("evidence_registry_sha256") or evidence_registry_sha256(), "model_card_id": provenance.get("model_card_id"),
        "model_card_version": provenance.get("model_card_version"), "provenance": provenance,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    if validate: validate_rolling_validation(artifact)
    return artifact


def write_rolling_validation_atomic(artifact: dict, path: Path = ROLLING_VALIDATION_OUTPUT) -> str:
    validate_rolling_validation(artifact)
    payload = json.dumps(artifact, indent=2, ensure_ascii=False, allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle: handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)
    return hashlib.sha256(payload).hexdigest()


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    print()
    print("=" * 62)
    print("  DengueOps AI - Phase 3: Temporal Backtest")
    print("=" * 62)

    # ── Load data ─────────────────────────────────────────────────────────────
    print("\n  Loading feature matrix...")
    df = load_feature_matrix()
    print(f"    Rows: {len(df)}  |  Cols: {len(df.columns)}")
    print(f"    Period: {df.iloc[0]['epi_year']} W{df.iloc[0]['epi_week']} "
          f"to {df.iloc[-1]['epi_year']} W{df.iloc[-1]['epi_week']}")

    # ── Run backtest ──────────────────────────────────────────────────────────
    print("\n  Running temporal backtest...")
    print(f"    Target         : {TARGET_COL} (14-day / 2-week ahead)")
    print(f"    Split          : {int(TRAIN_FRACTION*100)}% train / "
          f"{100 - int(TRAIN_FRACTION*100)}% test (chronological)")

    context = _run_backtest_context(df)
    results = context.result
    results.update({"validation_role": "legacy_single_holdout", "primary_validation_method": "expanding_window_rolling_origin",
                    "primary_validation_artifact": "data/rolling_validation.json"})
    rolling = build_rolling_validation(df)
    write_rolling_validation_atomic(rolling)

    if context.provenance and context.provenance.get("deployment_profile_id"):
        profile = load_deployment_profile(context.provenance["deployment_profile_id"])
        explainability = build_model_explainability(
            context.validation_model,
            context.train_df,
            context.test_df,
            context.feature_names,
            context.target,
            context.model_parameters,
            context.provenance,
            profile,
        )
        write_explainability_atomic(explainability, EXPLAINABILITY_OUTPUT)
        print(f"  Explainability: {EXPLAINABILITY_OUTPUT}")
    elif EXPLAINABILITY_OUTPUT.exists():
        EXPLAINABILITY_OUTPUT.unlink()

    # ── Print metrics ─────────────────────────────────────────────────────────
    print(f"\n  Train period  : "
          f"{results['train_period']['epi_year_start']} "
          f"W{results['train_period']['epi_week_start']} "
          f"to {results['train_period']['epi_year_end']} "
          f"W{results['train_period']['epi_week_end']} "
          f"({results['train_rows']} rows)")
    print(f"  Test period   : "
          f"{results['test_period']['epi_year_start']} "
          f"W{results['test_period']['epi_week_start']} "
          f"to {results['test_period']['epi_year_end']} "
          f"W{results['test_period']['epi_week_end']} "
          f"({results['test_rows']} rows)")

    print("\n  Metrics (target: cases 2 weeks ahead):")
    header = f"  {'Model':<26}  {'MAE':>8}  {'RMSE':>8}  {'MAPE (%)':>10}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for model_name, m in results["metrics"].items():
        tag = " <-- best" if model_name == results["best_model"] else ""
        print(f"  {model_name:<26}  {m['mae']:>8.1f}  {m['rmse']:>8.1f}  "
              f"{m['mape']:>10.1f}{tag}")

    print(f"\n  Best model by MAE: {results['best_model']}")

    # ── Save JSON ─────────────────────────────────────────────────────────────
    VALIDATION_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with open(VALIDATION_OUTPUT, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n  Saved: {VALIDATION_OUTPUT}")
    print()
    print("=" * 62)
    print("  Backtest complete.")
    print("=" * 62)
    print()


if __name__ == "__main__":
    main()
