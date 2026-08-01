"""Governed temporal feature availability and rolling-origin leakage checks."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from runtime_context import ROOT


POLICY_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "feature_availability_policy.json"
SCHEMA_PATH = ROOT / "config" / "feature_availability_policy.schema.json"


class TemporalLeakageError(ValueError):
    """Raised when governed time availability cannot be proven."""


def canonical_policy_sha256(policy: Mapping[str, Any]) -> str:
    value = dict(policy)
    value.pop("policy_sha256", None)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_and_validate_feature_availability_policy(
    deployment_id: str = "dhaka_south", expected_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    if deployment_id != "dhaka_south":
        raise TemporalLeakageError("Temporal validation policy deployment is unsupported.")
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TemporalLeakageError("Temporal validation policy is unavailable.") from exc
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(policy)]
    digest = canonical_policy_sha256(policy)
    if policy.get("policy_sha256") != digest or expected_sha256 not in (None, digest):
        errors.append("Temporal validation policy hash mismatch.")
    if errors:
        raise TemporalLeakageError(" ".join(dict.fromkeys(errors)))
    return policy, digest


def required_target_purge_rows(policy: Mapping[str, Any]) -> int:
    target = policy.get("target", {})
    horizon = target.get("horizon_weeks")
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise TemporalLeakageError("Target horizon is invalid.")
    if target.get("purge_rule") != "training_target_outcome_strictly_before_validation_forecast_origin":
        raise TemporalLeakageError("Target purge rule is unavailable.")
    return horizon


def audit_feature_availability(policy: Mapping[str, Any], feature_columns: Sequence[str]) -> None:
    features = policy.get("features")
    if not isinstance(features, list) or [item.get("feature_id") for item in features] != list(feature_columns):
        raise TemporalLeakageError("Feature availability policy does not match the governed feature order.")
    for feature in features:
        feature_id = str(feature.get("feature_id", ""))
        transform = feature.get("transformation", {})
        if feature.get("future_data_allowed") is not False:
            raise TemporalLeakageError(f"Future data is allowed for predictive feature {feature_id}.")
        if feature.get("source") not in {"dengue_cases", "climate_observation", "calendar"}:
            raise TemporalLeakageError(f"Predictive feature {feature_id} has an unavailable source.")
        shift = transform.get("shift_weeks")
        if isinstance(shift, bool) or not isinstance(shift, int) or shift < 0:
            raise TemporalLeakageError(f"Predictive feature {feature_id} uses a negative shift.")
        if transform.get("center") is not False:
            raise TemporalLeakageError(f"Predictive feature {feature_id} uses a centered window.")
        if transform.get("fill_method") != "none":
            raise TemporalLeakageError(f"Predictive feature {feature_id} uses future-looking fill behavior.")
        minimum_lag = feature.get("minimum_lag_weeks")
        if isinstance(minimum_lag, bool) or not isinstance(minimum_lag, int) or minimum_lag < 0:
            raise TemporalLeakageError(f"Predictive feature {feature_id} has an invalid availability lag.")
        if feature.get("availability_type") != "calendar_known_in_advance" and minimum_lag < 1:
            raise TemporalLeakageError(f"Observed predictive feature {feature_id} is not available before origin.")
        if transform.get("operation") in {"shift", "rolling", "ratio_of_lags"} and shift < minimum_lag:
            raise TemporalLeakageError(f"Predictive feature {feature_id} contradicts its availability lag.")
    preprocessing = policy.get("preprocessing", {})
    if preprocessing.get("learned_fit_scope") != "fold_training_rows_only" \
            or preprocessing.get("missing_value_strategy") != "drop_incomplete_rows_no_imputation":
        raise TemporalLeakageError("Fold-local preprocessing policy is unavailable.")


def audit_preprocessing_registry(registry: Mapping[str, Any]) -> None:
    for candidate in registry.get("candidates", []):
        if candidate.get("candidate_class") != "learned_model":
            continue
        preprocessing = candidate.get("preprocessing", {})
        if preprocessing.get("type") != "none" and preprocessing.get("fit_scope") != "fold_training_rows_only":
            raise TemporalLeakageError(f"Candidate {candidate.get('model_id')} preprocessing is not fold-local.")


def audit_fold_boundaries(
    rows: Sequence[Mapping[str, Any]], folds: Sequence[Mapping[str, Any]], policy: Mapping[str, Any],
) -> None:
    purge = required_target_purge_rows(policy)
    periods: list[date] = []
    for row in rows:
        try:
            periods.append(date.fromisocalendar(int(row["epi_year"]), int(row["epi_week"]), 1))
        except (KeyError, TypeError, ValueError) as exc:
            raise TemporalLeakageError("Feature observation identity is invalid.") from exc
    if len(periods) != len(set(periods)) or any(b != a + timedelta(weeks=1) for a, b in zip(periods, periods[1:])):
        raise TemporalLeakageError("Duplicate or non-contiguous observation identities cross temporal folds.")
    for fold in folds:
        validation_index = int(fold["validationIndex"])
        train_end = int(fold["trainEndExclusive"])
        if train_end > validation_index - purge:
            raise TemporalLeakageError("A training target overlaps the validation forecast origin.")
        if train_end < 1 or train_end > len(rows) or validation_index >= len(rows):
            raise TemporalLeakageError("Temporal fold indexes are invalid.")
        if periods[train_end - 1] >= periods[validation_index]:
            raise TemporalLeakageError("Training feature availability reaches the validation origin.")
        target_outcome = periods[train_end - 1] + timedelta(weeks=purge)
        if target_outcome >= periods[validation_index]:
            raise TemporalLeakageError("Training target availability reaches the validation origin.")
        values = [float(rows[train_end - 1][feature["feature_id"]]) for feature in policy["features"]]
        if not all(math.isfinite(value) for value in values):
            raise TemporalLeakageError("Temporal fold contains a non-finite predictive feature.")


def evidence(policy: Mapping[str, Any], digest: str, fold_count: int) -> dict[str, Any]:
    return {
        "validationStrategy": "rolling_origin_expanding_window",
        "foldCountRequired": int(fold_count),
        "foldCountCompleted": int(fold_count),
        "targetHorizonWeeks": int(policy["target"]["horizon_weeks"]),
        "purgeGapWeeks": required_target_purge_rows(policy),
        "featureAvailabilityPolicy": {
            "policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": digest,
        },
        "preprocessingScope": policy["preprocessing"]["learned_fit_scope"],
        "datasetSnapshotClassification": policy["dataset_snapshot"]["classification"],
        "trueHistoricalVintageDataAvailable": policy["dataset_snapshot"]["historical_vintages_available"],
        "qualificationScope": policy["qualification"]["classification"],
        "qualificationUntouchedHoldout": policy["qualification"]["untouched_scientific_holdout"],
        "leakageAuditStatus": "passed",
    }
