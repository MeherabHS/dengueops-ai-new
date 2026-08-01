from __future__ import annotations

import copy
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from feature_engineering import FEATURE_COLUMNS, add_lag_features, add_trend_features  # noqa: E402
from runtime_assessment import build_common_fold_plan  # noqa: E402
from runtime_assessment_policy import load_and_validate_assessment_policy  # noqa: E402
from temporal_leakage import (  # noqa: E402
    TemporalLeakageError,
    audit_feature_availability,
    audit_fold_boundaries,
    audit_preprocessing_registry,
    load_and_validate_feature_availability_policy,
    required_target_purge_rows,
)


def _policy():
    policy, _ = load_and_validate_feature_availability_policy()
    return policy


def _mutated_feature(feature_id: str, **changes):
    policy = copy.deepcopy(_policy())
    feature = next(item for item in policy["features"] if item["feature_id"] == feature_id)
    for key, value in changes.items():
        if key.startswith("transformation_"):
            feature["transformation"][key.removeprefix("transformation_")] = value
        else:
            feature[key] = value
    return policy


def _frame(rows: int = 160) -> pd.DataFrame:
    start = date.fromisocalendar(2021, 1, 1)
    values = []
    for index in range(rows):
        monday = start + timedelta(weeks=index)
        year, week, _ = monday.isocalendar()
        row = {"epi_year": year, "epi_week": week, "cases": float(index + 10), "target_cases_next_2w": float(index + 12)}
        row.update({feature: float(index + position + 1) for position, feature in enumerate(FEATURE_COLUMNS)})
        values.append(row)
    return pd.DataFrame(values)


def test_governed_feature_availability_covers_exact_predictive_contract():
    policy = _policy()
    audit_feature_availability(policy, FEATURE_COLUMNS)
    assert [item["feature_id"] for item in policy["features"]] == FEATURE_COLUMNS
    assert required_target_purge_rows(policy) == 2
    assert policy["dataset_snapshot"] == {
        "classification": "retrospective_latest_revision",
        "historical_vintages_available": False,
        "revision_identity_available": False,
    }


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        (_mutated_feature("cases_lag_1w", source="target"), "unavailable source"),
        (_mutated_feature("cases_lag_1w", transformation_shift_weeks=-1), "negative shift"),
        (_mutated_feature("cases_rolling_4w", transformation_center=True), "centered window"),
        (_mutated_feature("cases_lag_1w", transformation_fill_method="backfill"), "future-looking fill"),
        (_mutated_feature("temp_lag_2w", minimum_lag_weeks=0), "not available before origin"),
    ],
)
def test_future_feature_negative_shift_centered_rolling_backfill_and_climate_traps_fail(policy, message):
    with pytest.raises(TemporalLeakageError, match=message):
        audit_feature_availability(policy, FEATURE_COLUMNS)


def test_backward_only_features_do_not_change_when_future_observations_change():
    raw = pd.DataFrame({
        "cases": np.arange(1, 31, dtype=float),
        "rainfall_mm": np.arange(101, 131, dtype=float),
        "avg_temp_c": np.arange(201, 231, dtype=float),
        "humidity_pct": np.arange(301, 331, dtype=float),
    })
    before = add_trend_features(add_lag_features(raw))
    changed = raw.copy()
    changed.loc[20:, ["cases", "rainfall_mm", "avg_temp_c", "humidity_pct"]] += 10000
    after = add_trend_features(add_lag_features(changed))
    pd.testing.assert_frame_equal(before.loc[:19], after.loc[:19])


def test_target_horizon_is_purged_from_every_expanding_fold():
    assessment_policy, _ = load_and_validate_assessment_policy("dhaka_south")
    temporal_policy = _policy()
    frame = _frame()
    folds, _ = build_common_fold_plan(frame, assessment_policy, temporal_policy)
    assert len(folds) == 54
    for fold in folds:
        assert fold["targetPurgeRows"] == 2
        assert fold["trainEndExclusive"] + 2 == fold["validationIndex"]
        assert fold["trainingRowCount"] >= 104
    audit_fold_boundaries(frame.to_dict("records"), folds, temporal_policy)


def test_duplicate_observation_identity_across_fold_boundary_is_rejected():
    assessment_policy, _ = load_and_validate_assessment_policy("dhaka_south")
    frame = _frame()
    folds, _ = build_common_fold_plan(frame, assessment_policy, _policy())
    rows = frame.to_dict("records")
    rows[106]["epi_year"], rows[106]["epi_week"] = rows[105]["epi_year"], rows[105]["epi_week"]
    with pytest.raises(TemporalLeakageError, match="Duplicate or non-contiguous"):
        audit_fold_boundaries(rows, folds, _policy())


def test_scaling_is_fit_on_training_fold_and_validation_extreme_cannot_change_it():
    train_x = np.asarray([[1.0], [2.0], [3.0]])
    train_y = np.asarray([1.0, 2.0, 3.0])
    pipeline = Pipeline([("scaler", StandardScaler()), ("model", Ridge())])
    pipeline.fit(train_x, train_y)
    mean_before = pipeline.named_steps["scaler"].mean_.copy()
    pipeline.predict(np.asarray([[1_000_000.0]]))
    np.testing.assert_array_equal(pipeline.named_steps["scaler"].mean_, mean_before)
    np.testing.assert_array_equal(mean_before, np.asarray([2.0]))


def test_global_scaling_or_imputation_registry_contract_is_rejected():
    for preprocessing in (
        {"type": "StandardScaler", "fit_scope": "all_rows_before_split"},
        {"type": "SimpleImputer", "fit_scope": "all_rows_before_split"},
    ):
        registry = {"candidates": [{"model_id": "unsafe", "candidate_class": "learned_model", "preprocessing": preprocessing}]}
        with pytest.raises(TemporalLeakageError, match="not fold-local"):
            audit_preprocessing_registry(registry)


def test_qualification_is_not_misclassified_as_untouched_holdout():
    qualification = _policy()["qualification"]
    assert qualification["participates_in_candidate_ranking"] is False
    assert qualification["untouched_scientific_holdout"] is False
    assert qualification["classification"] == "workflow_execution_on_assessment_history"
