"""Pure mathematics and reconciliation helpers for runtime assessment evidence."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


SELECTION_STAGES = (
    ("mae", "mae"),
    ("rmse", "rmse"),
    ("wape", "wape"),
    ("median_absolute_error", "medianAbsoluteError"),
    ("maximum_absolute_error", "maximumAbsoluteError"),
)
NONNEGATIVE_RAW_MODEL_IDS = {
    "previous_week_naive",
    "moving_average_4w",
    "seasonal_naive_52w",
    "poisson_regression",
    "random_forest",
}


class AssessmentEvidenceError(ValueError):
    """Raised when assessment evidence is mathematically inconsistent."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prediction_evidence(
    model_id: str,
    actual: float,
    raw: float,
    runtime_seconds: float,
    warning_codes: Sequence[str],
) -> dict[str, Any]:
    if not math.isfinite(actual) or actual < 0:
        raise AssessmentEvidenceError("invalid_actual_target")
    if not math.isfinite(raw):
        raise AssessmentEvidenceError("nonfinite_prediction")
    if model_id in NONNEGATIVE_RAW_MODEL_IDS and raw < 0:
        raise AssessmentEvidenceError("prohibited_negative_prediction")
    if not math.isfinite(runtime_seconds) or runtime_seconds < 0:
        raise AssessmentEvidenceError("invalid_runtime")
    published = max(0.0, raw)
    signed = published - actual
    return {
        "modelId": model_id,
        "foldStatus": "warning" if warning_codes else "success",
        "rawPrediction": raw,
        "publishedPrediction": published,
        "clippingApplied": raw < 0,
        "signedError": signed,
        "absoluteError": abs(signed),
        "squaredError": signed * signed,
        "failureReasonCode": None,
        "warningCodes": list(warning_codes),
        "runtimeSeconds": runtime_seconds,
    }


def failed_prediction(
    model_id: str,
    reason: str,
    runtime_seconds: float = 0.0,
    warning_codes: Sequence[str] | None = None,
) -> dict[str, Any]:
    if not math.isfinite(runtime_seconds) or runtime_seconds < 0:
        raise AssessmentEvidenceError("invalid_runtime")
    return {
        "modelId": model_id,
        "foldStatus": "failed",
        "rawPrediction": None,
        "publishedPrediction": None,
        "clippingApplied": False,
        "signedError": None,
        "absoluteError": None,
        "squaredError": None,
        "failureReasonCode": reason,
        "warningCodes": list(warning_codes or []),
        "runtimeSeconds": runtime_seconds,
    }


def aggregate_candidate(
    records: Sequence[Mapping[str, Any]], actuals: Sequence[float]
) -> dict[str, Any] | None:
    if len(records) != len(actuals):
        raise AssessmentEvidenceError("candidate_actual_sequence_mismatch")
    successful = [
        record for record in records if record["foldStatus"] in {"success", "warning"}
    ]
    if not successful:
        return None
    absolute = np.asarray(
        [record["absoluteError"] for record in successful], dtype=float
    )
    squared = np.asarray(
        [record["squaredError"] for record in successful], dtype=float
    )
    if not np.isfinite(absolute).all() or not np.isfinite(squared).all():
        raise AssessmentEvidenceError("nonfinite_candidate_error")
    successful_actuals = [
        actual
        for actual, record in zip(actuals, records)
        if record["foldStatus"] in {"success", "warning"}
    ]
    denominator = float(sum(successful_actuals))
    return {
        "mae": float(absolute.mean()),
        "rmse": float(np.sqrt(squared.mean())),
        "wape": float(100 * absolute.sum() / denominator) if denominator else None,
        "medianAbsoluteError": float(np.median(absolute)),
        "maximumAbsoluteError": float(absolute.max()),
        "clippingCount": sum(bool(record["clippingApplied"]) for record in successful),
        "warningCount": sum(len(record["warningCodes"]) for record in successful),
        "runtimeSeconds": float(sum(float(record["runtimeSeconds"]) for record in records)),
    }


def selection_eligible(
    *, policy_eligible: bool, successful_folds: int, failed_folds: int,
    metrics: Mapping[str, Any] | None, required_folds: int,
) -> bool:
    if not policy_eligible or successful_folds != required_folds or failed_folds != 0 or metrics is None:
        return False
    for _, key in SELECTION_STAGES:
        value = metrics.get(key)
        if value is None or not math.isfinite(float(value)):
            return False
    return True


def _choose_candidate(
    candidates: Sequence[Mapping[str, Any]], tolerance: float
) -> tuple[Mapping[str, Any], str, list[str]]:
    remaining = list(candidates)
    if not remaining:
        raise AssessmentEvidenceError("no_selection_eligible_candidates")
    steps: list[str] = []
    tie_stage = "mae"
    for stage, key in SELECTION_STAGES:
        values = [candidate["metrics"].get(key) for candidate in remaining]
        if any(value is None or not math.isfinite(float(value)) for value in values):
            raise AssessmentEvidenceError(f"unavailable_selection_metric:{stage}")
        best = min(float(value) for value in values)
        remaining = [
            candidate
            for candidate in remaining
            if abs(float(candidate["metrics"][key]) - best) <= tolerance
        ]
        steps.append(
            f"{stage}: retained {','.join(str(candidate['modelId']) for candidate in remaining)}"
        )
        tie_stage = stage
        if len(remaining) == 1:
            return remaining[0], tie_stage, steps
    best_rank = min(int(candidate["selectionComplexityRank"]) for candidate in remaining)
    remaining = [
        candidate
        for candidate in remaining
        if int(candidate["selectionComplexityRank"]) == best_rank
    ]
    steps.append(
        "selection_complexity_rank: retained "
        + ",".join(str(candidate["modelId"]) for candidate in remaining)
    )
    tie_stage = "selection_complexity_rank"
    if len(remaining) > 1:
        remaining.sort(key=lambda candidate: str(candidate["modelId"]))
        steps.append(f"model_id: retained {remaining[0]['modelId']}")
        tie_stage = "model_id"
    return remaining[0], tie_stage, steps


def select_technical_winner(
    candidate_results: Sequence[Mapping[str, Any]], tolerance: float = 1e-9
) -> tuple[str | None, str | None, list[str], list[str]]:
    remaining = [candidate for candidate in candidate_results if candidate["selectionEligible"]]
    eligible_ids = [str(candidate["modelId"]) for candidate in remaining]
    if len(remaining) < 2:
        return None, None, [], []
    steps: list[str] = []
    tie_stage: str | None = None
    for stage, key in SELECTION_STAGES:
        values = [candidate["metrics"].get(key) for candidate in remaining]
        if any(value is None or not math.isfinite(float(value)) for value in values):
            return None, stage, steps + [f"{stage}: unavailable metric prevented deterministic selection"], eligible_ids
        best = min(float(value) for value in values)
        remaining = [
            candidate for candidate in remaining
            if abs(float(candidate["metrics"][key]) - best) <= tolerance
        ]
        steps.append(f"{stage}: retained {','.join(str(candidate['modelId']) for candidate in remaining)}")
        tie_stage = stage
        if len(remaining) == 1:
            return str(remaining[0]["modelId"]), tie_stage, steps, eligible_ids
    best_rank = min(int(candidate["selectionComplexityRank"]) for candidate in remaining)
    remaining = [candidate for candidate in remaining if int(candidate["selectionComplexityRank"]) == best_rank]
    steps.append("selection_complexity_rank: retained " + ",".join(str(candidate["modelId"]) for candidate in remaining))
    tie_stage = "selection_complexity_rank"
    if len(remaining) > 1:
        remaining.sort(key=lambda candidate: str(candidate["modelId"]))
        steps.append(f"model_id: retained {remaining[0]['modelId']}")
        tie_stage = "model_id"
    return str(remaining[0]["modelId"]), tie_stage, steps, eligible_ids


def display_order(
    candidate_results: Sequence[Mapping[str, Any]],
    registry_order: Sequence[str],
    tolerance: float = 1e-9,
) -> list[str]:
    remaining = [candidate for candidate in candidate_results if candidate["selectionEligible"]]
    ordered: list[str] = []
    while remaining:
        winner, _, _ = _choose_candidate(remaining, tolerance)
        ordered.append(str(winner["modelId"]))
        remaining = [candidate for candidate in remaining if candidate is not winner]
    registry_rank = {model_id: index for index, model_id in enumerate(registry_order)}
    ineligible = sorted(
        (candidate for candidate in candidate_results if not candidate["selectionEligible"]),
        key=lambda candidate: (
            registry_rank.get(str(candidate["modelId"]), len(registry_rank)),
            str(candidate["modelId"]),
        ),
    )
    return ordered + [str(candidate["modelId"]) for candidate in ineligible]


def public_fold_plan(folds: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    excluded = {
        "trainStartIndex", "trainEndExclusive", "embargoIndex", "validationIndex", "predictions"
    }
    return [{key: value for key, value in fold.items() if key not in excluded} for fold in folds]


def fold_plan_sha256(folds: Iterable[Mapping[str, Any]]) -> str:
    return canonical_sha256(public_fold_plan(folds))


def matrix_sha256(
    rows: Sequence[Mapping[str, Any]], feature_columns: Sequence[str], target_column: str
) -> str:
    canonical_rows = [
        {
            "epi_year": int(row["epi_year"]),
            "epi_week": int(row["epi_week"]),
            "features": [float(row[name]) for name in feature_columns],
            "target": float(row[target_column]),
        }
        for row in rows
    ]
    return canonical_sha256(canonical_rows)


def validate_folds_against_feature_rows(
    folds: Sequence[Mapping[str, Any]],
    rows: Sequence[Mapping[str, Any]],
    feature_columns: Sequence[str],
    target_column: str,
    *,
    labelled_row_count: int,
    selected_validation_indexes: Sequence[int],
    initial_training_rows: int,
    embargo_rows: int,
) -> None:
    if len(rows) != labelled_row_count or len(folds) != len(selected_validation_indexes):
        raise AssessmentEvidenceError("invalid_feature_row_count")
    periods: list[date] = []
    for row in rows:
        try:
            monday = date.fromisocalendar(int(row["epi_year"]), int(row["epi_week"]), 1)
        except (TypeError, ValueError) as exc:
            raise AssessmentEvidenceError("invalid_feature_period") from exc
        if int(row["epi_week"]) == 53:
            raise AssessmentEvidenceError("unsupported_feature_week_53")
        periods.append(monday)
        values = [float(row[name]) for name in feature_columns]
        target = float(row[target_column])
        if not all(math.isfinite(value) for value in values) or not math.isfinite(target) or target < 0:
            raise AssessmentEvidenceError("invalid_feature_matrix_value")
    if len(set(periods)) != len(periods) or any(
        current != previous + timedelta(weeks=1)
        for previous, current in zip(periods, periods[1:])
    ):
        raise AssessmentEvidenceError("invalid_feature_chronology")
    for fold, validation_index in zip(folds, selected_validation_indexes):
        if validation_index < initial_training_rows + embargo_rows or validation_index >= len(rows):
            raise AssessmentEvidenceError("invalid_validation_index")
        train_end = validation_index - embargo_rows
        validation = rows[validation_index]
        embargo = rows[train_end]
        training = rows[:train_end]
        period = lambda row: f"{int(row['epi_year'])}-W{int(row['epi_week']):02d}"
        if fold.get("forecastOrigin") != period(validation):
            raise AssessmentEvidenceError("feature_origin_mismatch")
        if float(fold["actualTarget"]) != float(validation[target_column]):
            raise AssessmentEvidenceError("feature_actual_target_mismatch")
        if fold.get("trainingRowCount") != len(training):
            raise AssessmentEvidenceError("feature_training_count_mismatch")
        if fold.get("trainingPeriod") != {
            "start": period(training[0]), "end": period(training[-1])
        }:
            raise AssessmentEvidenceError("feature_training_period_mismatch")
        if fold.get("embargoPeriod") != period(embargo):
            raise AssessmentEvidenceError("feature_embargo_period_mismatch")
        if fold.get("trainingMatrixSha256") != matrix_sha256(training, feature_columns, target_column):
            raise AssessmentEvidenceError("training_matrix_hash_mismatch")
        if fold.get("validationMatrixSha256") != matrix_sha256([validation], feature_columns, target_column):
            raise AssessmentEvidenceError("validation_matrix_hash_mismatch")


def validate_fold_identities(
    folds: Sequence[Mapping[str, Any]], candidate_ids: Sequence[str], *,
    selected_validation_indexes: Sequence[int], initial_training_rows: int,
    embargo_rows: int, horizon_weeks: int,
) -> tuple[list[float], dict[str, list[Mapping[str, Any]]]]:
    if len(folds) != len(selected_validation_indexes) or not folds or len(candidate_ids) != 7 or len(set(candidate_ids)) != 7:
        raise AssessmentEvidenceError("invalid_fold_or_candidate_count")
    records: dict[str, list[Mapping[str, Any]]] = {model_id: [] for model_id in candidate_ids}
    actuals: list[float] = []
    fold_ids: set[str] = set()
    previous_origin: date | None = None
    for sequence, (fold, validation_index) in enumerate(zip(folds, selected_validation_indexes), 1):
        if fold.get("sequence") != sequence:
            raise AssessmentEvidenceError("invalid_fold_sequence")
        origin = str(fold.get("forecastOrigin"))
        target = str(fold.get("targetPeriod"))
        try:
            origin_year, origin_week = int(origin[:4]), int(origin[6:])
            origin_monday = date.fromisocalendar(origin_year, origin_week, 1)
            target_monday = origin_monday + timedelta(weeks=horizon_weeks)
            target_year, target_week, _ = target_monday.isocalendar()
        except (TypeError, ValueError) as exc:
            raise AssessmentEvidenceError("invalid_fold_period") from exc
        expected_target = f"{target_year}-W{target_week:02d}"
        expected_id = f"rolling-origin-{sequence:04d}-{origin}-to-{expected_target}"
        if target != expected_target or fold.get("foldId") != expected_id:
            raise AssessmentEvidenceError("fold_target_or_identity_mismatch")
        if previous_origin is not None and origin_monday != previous_origin + timedelta(weeks=1):
            raise AssessmentEvidenceError("noncontiguous_fold_origins")
        previous_origin = origin_monday
        fold_id = str(fold["foldId"])
        if fold_id in fold_ids:
            raise AssessmentEvidenceError("duplicate_fold_id")
        fold_ids.add(fold_id)
        expected_training_count = validation_index - embargo_rows
        if expected_training_count < initial_training_rows or fold.get("trainingRowCount") != expected_training_count:
            raise AssessmentEvidenceError("training_row_count_mismatch")
        actual = float(fold["actualTarget"])
        if not math.isfinite(actual) or actual < 0:
            raise AssessmentEvidenceError("invalid_actual_target")
        actuals.append(actual)
        predictions = fold.get("predictions")
        if not isinstance(predictions, list) or len(predictions) != 7:
            raise AssessmentEvidenceError("incomplete_candidate_evidence")
        if {prediction.get("modelId") for prediction in predictions} != set(candidate_ids):
            raise AssessmentEvidenceError("candidate_set_mismatch")
        for prediction in predictions:
            records[str(prediction["modelId"])].append(prediction)
    return actuals, records


def validate_prediction_record(
    model_id: str, actual: float, record: Mapping[str, Any]
) -> None:
    runtime_seconds = float(record["runtimeSeconds"])
    if not math.isfinite(runtime_seconds) or runtime_seconds < 0:
        raise AssessmentEvidenceError("invalid_runtime")
    status = record.get("foldStatus")
    if status == "failed":
        expected_null = (
            record.get("rawPrediction"), record.get("publishedPrediction"),
            record.get("signedError"), record.get("absoluteError"), record.get("squaredError")
        )
        if any(value is not None for value in expected_null) or record.get("clippingApplied") is not False:
            raise AssessmentEvidenceError("invalid_failed_prediction_evidence")
        if not record.get("failureReasonCode"):
            raise AssessmentEvidenceError("missing_failure_reason")
        return
    if status not in {"success", "warning"}:
        raise AssessmentEvidenceError("invalid_fold_status")
    expected = prediction_evidence(
        model_id,
        actual,
        float(record["rawPrediction"]),
        runtime_seconds,
        list(record["warningCodes"]),
    )
    if status != expected["foldStatus"]:
        raise AssessmentEvidenceError("warning_status_mismatch")
    for key in (
        "publishedPrediction", "clippingApplied", "signedError", "absoluteError",
        "squaredError", "failureReasonCode",
    ):
        if record.get(key) != expected[key]:
            raise AssessmentEvidenceError(f"prediction_evidence_mismatch:{key}")
