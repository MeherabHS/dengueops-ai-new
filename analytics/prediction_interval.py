"""Governed candidate-specific intervals from B9.L rolling-origin OOF residuals."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator, FormatChecker

from runtime_context import ROOT


POLICY_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "forecast_uncertainty_policy.json"
SCHEMA_PATH = ROOT / "config" / "forecast_uncertainty_policy.schema.json"
METHOD_ID = "rolling_origin_oof_absolute_residual_v1"
METHOD_VERSION = "b9.pi-v1"


class PredictionIntervalError(ValueError):
    """Raised when calibration evidence is invalid or cannot be reconciled."""


def canonical_policy_sha256(policy: Mapping[str, Any]) -> str:
    value = dict(policy)
    value.pop("policy_sha256", None)
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_and_validate_uncertainty_policy(
    deployment_id: str = "dhaka_south", expected_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    if deployment_id != "dhaka_south":
        raise PredictionIntervalError("Forecast uncertainty policy deployment is unsupported.")
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PredictionIntervalError("Forecast uncertainty policy is unavailable.") from exc
    errors = [error.message for error in Draft202012Validator(schema).iter_errors(policy)]
    digest = canonical_policy_sha256(policy)
    if policy.get("policy_sha256") != digest or expected_sha256 not in (None, digest):
        errors.append("Forecast uncertainty policy hash mismatch.")
    if errors:
        raise PredictionIntervalError(" ".join(dict.fromkeys(errors)))
    return policy, digest


def finite_sample_quantile(values: Sequence[float], nominal_level: float) -> tuple[int, float]:
    if not 0 < nominal_level < 1 or not values:
        raise PredictionIntervalError("A valid nominal level and nonempty residual pool are required.")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise PredictionIntervalError("Calibration residuals must be finite and nonnegative.")
    rank = max(1, min(len(ordered), math.ceil((len(ordered) + 1) * nominal_level)))
    return rank, ordered[rank - 1]


def construct_count_interval(point_raw: float, quantile: float) -> dict[str, float | int | bool]:
    if not math.isfinite(point_raw) or point_raw < 0 or not math.isfinite(quantile) or quantile < 0:
        raise PredictionIntervalError("Point forecast and residual quantile must be finite and nonnegative.")
    lower_unclipped = point_raw - quantile
    lower_raw = max(0.0, lower_unclipped)
    upper_raw = point_raw + quantile
    lower_reported = math.floor(lower_raw)
    upper_reported = math.ceil(upper_raw)
    if not (0 <= lower_raw <= point_raw <= upper_raw and lower_reported <= round(point_raw) <= upper_reported):
        raise PredictionIntervalError("Prediction interval bounds do not contain the point forecast.")
    return {
        "lowerRawUnclipped": lower_unclipped,
        "lowerRaw": lower_raw,
        "upperRaw": upper_raw,
        "lowerReported": lower_reported,
        "upperReported": upper_reported,
        "lowerClippingApplied": lower_raw != lower_unclipped,
    }


def _candidate_residuals(folds: Sequence[Mapping[str, Any]], candidate_id: str) -> list[dict[str, Any]]:
    residuals: list[dict[str, Any]] = []
    for fold in folds:
        matches = [item for item in fold.get("predictions", []) if item.get("modelId") == candidate_id]
        if len(matches) != 1:
            raise PredictionIntervalError(f"Candidate {candidate_id} does not have one OOF record per fold.")
        prediction = matches[0]
        if prediction.get("foldStatus") not in {"success", "warning"}:
            return []
        actual = float(fold["actualTarget"])
        raw = float(prediction["rawPrediction"])
        absolute = abs(actual - raw)
        if not all(math.isfinite(value) for value in (actual, raw, absolute)) or actual < 0:
            raise PredictionIntervalError("OOF calibration contains invalid numeric evidence.")
        if not math.isclose(float(prediction["absoluteError"]), absolute, rel_tol=1e-12, abs_tol=1e-12):
            raise PredictionIntervalError("OOF residual does not reconcile with actual and prediction.")
        residuals.append({
            "foldId": fold["foldId"], "forecastOrigin": fold["forecastOrigin"],
            "targetPeriod": fold["targetPeriod"], "actualTarget": actual,
            "rawPrediction": raw, "absoluteResidual": absolute,
        })
    return residuals


def build_assessment_calibration(
    folds: Sequence[Mapping[str, Any]], candidate_ids: Sequence[str], scientific_validation: Mapping[str, Any],
    policy: Mapping[str, Any], policy_sha256: str,
) -> dict[str, Any]:
    source = policy["permitted_calibration_source"]
    feature_policy = scientific_validation.get("featureAvailabilityPolicy", {})
    compatible = (
        scientific_validation.get("validationStrategy") == "rolling_origin_expanding_window"
        and scientific_validation.get("leakageAuditStatus") == source["leakage_audit_status"]
        and feature_policy.get("policyId") == source["validation_policy_id"]
        and feature_policy.get("policyVersion") == source["validation_policy_version"]
        and scientific_validation.get("foldCountCompleted") == len(folds)
        and scientific_validation.get("foldCountRequired") == len(folds)
    )
    if not compatible:
        raise PredictionIntervalError("Assessment is not compatible with the governed B9.L calibration source.")
    minimum = int(policy["minimum_calibration_observations"])
    level = float(policy["nominal_interval_level"])
    summaries = []
    for candidate_id in candidate_ids:
        residuals = _candidate_residuals(folds, candidate_id)
        if len(residuals) < minimum:
            summaries.append({
                "candidateId": candidate_id, "status": "point_only", "reason": "insufficient_calibration_evidence",
                "sampleCount": len(residuals), "minimumRequired": minimum,
                "quantileRank": None, "absoluteResidualQuantile": None,
            })
            continue
        rank, quantile = finite_sample_quantile([row["absoluteResidual"] for row in residuals], level)
        summaries.append({
            "candidateId": candidate_id, "status": "available", "reason": None,
            "sampleCount": len(residuals), "minimumRequired": minimum,
            "quantileRank": rank, "absoluteResidualQuantile": quantile,
        })
    return {
        "policy": {"policyId": policy["policy_id"], "policyVersion": policy["policy_version"], "policySha256": policy_sha256},
        "method": policy["method"], "nominalLevel": level,
        "residualDefinition": policy["residual_definition"], "quantileRule": policy["quantile_rule"],
        "sourceValidationStrategy": scientific_validation["validationStrategy"],
        "sourceValidationPolicy": feature_policy, "leakageAuditStatus": scientific_validation["leakageAuditStatus"],
        "snapshotClassification": scientific_validation["datasetSnapshotClassification"],
        "candidateCalibrations": summaries,
    }


def verify_assessment_calibration(rolling: Mapping[str, Any]) -> dict[str, Any]:
    evidence = rolling.get("uncertaintyCalibration")
    if not isinstance(evidence, dict):
        raise PredictionIntervalError("calibration_not_available_for_assignment")
    policy_ref = evidence.get("policy", {})
    policy, policy_sha = load_and_validate_uncertainty_policy(
        str(rolling.get("deploymentId")), str(policy_ref.get("policySha256", "")),
    )
    expected = build_assessment_calibration(
        rolling.get("folds", []), rolling.get("candidateIds", []), rolling.get("scientificValidation", {}),
        policy, policy_sha,
    )
    if evidence != expected:
        raise PredictionIntervalError("Committed assessment calibration evidence does not recompute.")
    return expected


def calibration_metrics(residuals: Sequence[Mapping[str, Any]], quantile: float) -> dict[str, Any]:
    widths: list[float] = []
    covered = lower_misses = upper_misses = 0
    for row in residuals:
        bounds = construct_count_interval(float(row["rawPrediction"]), quantile)
        actual = float(row["actualTarget"])
        widths.append(float(bounds["upperRaw"]) - float(bounds["lowerRaw"]))
        if actual < float(bounds["lowerRaw"]): lower_misses += 1
        elif actual > float(bounds["upperRaw"]): upper_misses += 1
        else: covered += 1
    return {
        "historicalCoverage": covered / len(residuals), "coveredFoldCount": covered,
        "evaluatedFoldCount": len(residuals), "lowerMissCount": lower_misses, "upperMissCount": upper_misses,
        "intervalWidthSummary": {"average": statistics.mean(widths), "median": statistics.median(widths),
            "minimum": min(widths), "maximum": max(widths)},
    }


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _strict_artifact(path: Path, schema_name: str) -> tuple[dict[str, Any], bytes]:
    try:
        bytes_value = path.read_bytes()
        value = json.loads(bytes_value.decode("utf-8"))
        schema = json.loads((ROOT / "config" / schema_name).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PredictionIntervalError("Calibration source evidence is unavailable.") from exc
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda item: list(item.path),
    )
    if errors or not isinstance(value, dict):
        raise PredictionIntervalError("Calibration source evidence failed strict validation.")
    return value, bytes_value


def resolve_assignment_calibration(
    runtime_root: Path, authority: Mapping[str, Any], candidate_id: str,
) -> dict[str, Any]:
    """Resolve and verify the exact source assessment named by the current assignment."""
    active_policy, active_policy_sha = load_and_validate_uncertainty_policy(str(authority.get("deploymentId", "dhaka_south")))
    active_policy_ref = {"policyId": active_policy["policy_id"], "policyVersion": active_policy["policy_version"], "policySha256": active_policy_sha}
    runtime_root = runtime_root.resolve()
    assignment_id = str(authority.get("assignmentId", ""))
    assignment_root = (runtime_root / "model-assignments" / assignment_id).resolve()
    if runtime_root not in assignment_root.parents:
        raise PredictionIntervalError("Assignment calibration path escaped runtime authority.")
    record, record_bytes = _strict_artifact(
        assignment_root / "artifacts" / "assignment_record.json", "runtime_model_assignment.schema.json",
    )
    commit, commit_bytes = _strict_artifact(
        assignment_root / "metadata" / "commit.json", "runtime_model_assignment_commit.schema.json",
    )
    if (
        record.get("assignmentId") != assignment_id
        or record.get("modelId") != candidate_id
        or record.get("candidateRegistrySha256") != authority.get("candidateRegistrySha256")
        or commit.get("assignmentId") != assignment_id
        or commit.get("assignmentRecordSha256") != _sha_bytes(record_bytes)
        or _sha_bytes(commit_bytes) != authority.get("assignmentCommitSha256")
    ):
        raise PredictionIntervalError("Assignment calibration source identity mismatch.")
    assessment_id = record.get("sourceAssessmentId")
    if not isinstance(assessment_id, str):
        return {"status": "point_only", "reason": "calibration_not_available_for_assignment", "policy": active_policy_ref,
            "method": active_policy["method"], "nominalLevel": active_policy["nominal_interval_level"],
            "minimumRequired": active_policy["minimum_calibration_observations"], "residuals": []}
    assessment_root = (runtime_root / "assessments" / assessment_id).resolve()
    if runtime_root not in assessment_root.parents:
        raise PredictionIntervalError("Assessment calibration path escaped runtime authority.")
    assessment_commit, assessment_commit_bytes = _strict_artifact(
        assessment_root / "metadata" / "commit.json", "runtime_assessment_commit.schema.json",
    )
    rolling, rolling_bytes = _strict_artifact(
        assessment_root / "artifacts" / "rolling_validation.json", "runtime_rolling_validation.schema.json",
    )
    assessment_commit_sha = _sha_bytes(assessment_commit_bytes)
    rolling_sha = _sha_bytes(rolling_bytes)
    if (
        assessment_commit.get("assessmentId") != assessment_id
        or assessment_commit.get("status") != "committed"
        or assessment_commit.get("candidateRegistrySha256") != authority.get("candidateRegistrySha256")
        or assessment_commit.get("artifactHashes", {}).get("rolling_validation.json") != rolling_sha
        or rolling.get("assessmentId") != assessment_id
        or rolling.get("candidateRegistrySha256") != authority.get("candidateRegistrySha256")
        or rolling.get("foldPlanSha256") != record.get("foldPlanSha256")
        or candidate_id not in rolling.get("candidateIds", [])
    ):
        raise PredictionIntervalError("Source assessment calibration identity mismatch.")
    if not isinstance(rolling.get("uncertaintyCalibration"), dict):
        return {
            "status": "point_only", "reason": "calibration_not_available_for_assignment",
            "sourceAssessmentId": assessment_id, "sourceAssessmentCommitSha256": assessment_commit_sha,
            "sourceRollingValidationSha256": rolling_sha,
            "sourceFoldPlanSha256": rolling["foldPlanSha256"], "sourceSnapshotClassification": None,
            "policy": active_policy_ref, "method": active_policy["method"],
            "nominalLevel": active_policy["nominal_interval_level"],
            "minimumRequired": active_policy["minimum_calibration_observations"], "residuals": [],
        }
    evidence = verify_assessment_calibration(rolling)
    summaries = [item for item in evidence["candidateCalibrations"] if item["candidateId"] == candidate_id]
    if len(summaries) != 1:
        raise PredictionIntervalError("Assigned candidate calibration is missing or ambiguous.")
    summary = summaries[0]
    result = {
        **summary,
        "sourceAssessmentId": assessment_id,
        "sourceAssessmentCommitSha256": assessment_commit_sha,
        "sourceRollingValidationSha256": rolling_sha,
        "sourceFoldPlanSha256": rolling["foldPlanSha256"],
        "sourceSnapshotClassification": evidence["snapshotClassification"],
        "policy": evidence["policy"], "method": evidence["method"], "nominalLevel": evidence["nominalLevel"],
        "residuals": _candidate_residuals(rolling["folds"], candidate_id),
    }
    if summary["status"] != "available":
        result["residuals"] = []
    elif len(result["residuals"]) != summary["sampleCount"]:
        raise PredictionIntervalError("Assigned candidate residual count changed.")
    return result
