"""Pure deterministic mathematics for evidence-only model-performance comparison."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any, Mapping, Sequence


class ModelDegradationMetricError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ModelDegradationMetricError("Evidence is not canonically serializable.") from exc


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelDegradationMetricError(f"{name} must be numeric.") from exc
    if not math.isfinite(number):
        raise ModelDegradationMetricError(f"{name} must be finite.")
    return number


def _period_date(value: str) -> datetime:
    try:
        year, week = value.split("-W")
        parsed = datetime.fromisocalendar(int(year), int(week), 1)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ModelDegradationMetricError("Target period must be a valid YYYY-Www period.") from exc
    if int(week) < 1 or int(week) > 52:
        raise ModelDegradationMetricError("Target period week must be between 01 and 52.")
    return parsed


def _run_id(record: Mapping[str, Any]) -> str:
    value = record.get("sourceForecastRunId", record.get("forecastRunId"))
    if not isinstance(value, str) or not value:
        raise ModelDegradationMetricError("Outcome source run identity is missing.")
    return value


def _period_start(record: Mapping[str, Any]) -> str:
    return str(record.get("forecastTargetPeriod", record.get("targetPeriodStart", "")))


def _period_end(record: Mapping[str, Any]) -> str:
    return str(record.get("targetPeriodEnd", _period_start(record)))


def ordered_outcomes(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    result = list(records)
    for record in result:
        _period_date(_period_start(record)); _period_date(_period_end(record)); _run_id(record)
        if not isinstance(record.get("outcomeId"), str):
            raise ModelDegradationMetricError("Outcome identity is missing.")
    return sorted(result, key=lambda item: (_period_date(_period_start(item)), _period_date(_period_end(item)), _run_id(item), str(item["outcomeId"])))


def _policy(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ModelDegradationMetricError("Policy identity must be an object.")
    result = {"policyId": str(value.get("policyId", "")), "policyVersion": str(value.get("policyVersion", "")), "policySha256": str(value.get("policySha256", ""))}
    if not result["policyId"] or not result["policyVersion"] or len(result["policySha256"]) != 64:
        raise ModelDegradationMetricError("Policy identity is incomplete.")
    return result


def strict_cohort_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    source_family = str(record.get("sourceFamily", "quick_forecast_p1" if record.get("schemaVersion") == "1.0" else ""))
    if source_family not in {"quick_forecast_p1", "approved_forecast_p1", "approved_forecast_p2"}:
        raise ModelDegradationMetricError("Unknown forecast source family.")
    monitoring = record.get("monitoringPolicy") or ({"policyId":"RUNTIME.FORECAST_OUTCOME.MONITORING","policyVersion":"p1.4g-v1","policySha256":"0121c2fad28b7b8e9080df52698593d1cab677febf4fa668e11f6f19541fb249"} if record.get("schemaVersion") == "1.0" else None)
    source = record.get("sourcePolicy") or {"policyId":record.get("forecastPolicyId"),"policyVersion":record.get("forecastPolicyVersion"),"policySha256":record.get("forecastPolicySha256")}
    evidence = record.get("sourceEvidence") if isinstance(record.get("sourceEvidence"), Mapping) else {}
    approved = source_family != "quick_forecast_p1"
    identity = {
        "deploymentId": record.get("deploymentId"), "geography": record.get("geography"),
        "target": record.get("targetColumn"), "forecastHorizonWeeks": record.get("forecastHorizonWeeks"),
        "sourceFamily": source_family, "monitoringPolicy": _policy(monitoring), "forecastPolicy": _policy(source),
        "modelId": record.get("modelId"), "modelFamily": record.get("modelFamily"),
        "parameterSha256": record.get("modelParametersSha256"), "featureOrderSha256": record.get("featureOrderSha256"),
        "candidateRegistrySha256": record.get("candidateRegistrySha256"),
        "assessmentPolicy": _policy(evidence.get("assessmentPolicy")) if approved else None,
        "decisionPolicy": _policy(evidence.get("decisionPolicy")) if approved else None,
        "uncertaintyStatus": record.get("empiricalRangeStatus"),
    }
    required = ("deploymentId","geography","target","forecastHorizonWeeks","modelId","modelFamily","parameterSha256","featureOrderSha256","candidateRegistrySha256","uncertaintyStatus")
    if any(identity[key] in (None, "") for key in required):
        raise ModelDegradationMetricError("Strict cohort identity is incomplete.")
    return identity


def strict_cohort_key(record: Mapping[str, Any]) -> str:
    return canonical_sha256(strict_cohort_identity(record))


def ordered_outcome_set_hash(records: Sequence[Mapping[str, Any]]) -> str:
    values = []
    for record in ordered_outcomes(records):
        evidence_hash = record.get("outcomeEvidenceSha256")
        if not isinstance(evidence_hash, str) or len(evidence_hash) != 64:
            raise ModelDegradationMetricError("Outcome evidence hash is missing.")
        values.append({"outcomeId":record["outcomeId"],"outcomeEvidenceSha256":evidence_hash})
    return canonical_sha256(values)


def period_warnings(records: Sequence[Mapping[str, Any]]) -> list[str]:
    ordered = ordered_outcomes(records); periods = [_period_start(item) for item in ordered]; warnings: list[str] = []
    if len(set(periods)) != len(periods): warnings.append("duplicate_target_periods_present")
    unique = sorted(set(periods), key=_period_date)
    for left, right in zip(unique, unique[1:]):
        cursor = _period_date(left) + timedelta(weeks=1)
        while cursor.isocalendar().week == 53: cursor += timedelta(weeks=1)
        if cursor != _period_date(right): warnings.append("calendar_gaps_present"); break
    return warnings


def select_monitoring_windows(records: Sequence[Mapping[str, Any]], outcome_count: int) -> dict[str, Any]:
    if isinstance(outcome_count, bool) or not isinstance(outcome_count, int) or outcome_count <= 0:
        raise ModelDegradationMetricError("Governed window size must be a positive integer.")
    ordered = ordered_outcomes(records); total = len(ordered)
    if total < outcome_count:
        return {"status":"insufficient_recent_outcomes","windowOutcomeCount":outcome_count,"availableOutcomeCount":total}
    if total < 2 * outcome_count:
        return {"status":"insufficient_reference_outcomes","windowOutcomeCount":outcome_count,"availableOutcomeCount":total}
    recent = ordered[-outcome_count:]; reference = ordered[-2*outcome_count:-outcome_count]; excluded = ordered[:-2*outcome_count]
    recent_ids = {str(item["outcomeId"]) for item in recent}; reference_ids = {str(item["outcomeId"]) for item in reference}
    if recent_ids & reference_ids: raise ModelDegradationMetricError("Reference and recent windows overlap.")
    def refs(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [{"outcomeId":v["outcomeId"],"outcomeEvidenceSha256":v["outcomeEvidenceSha256"]} for v in values]
    reference_refs, recent_refs, excluded_refs = refs(reference), refs(recent), refs(excluded)
    return {"status":"computable_descriptive_evidence","windowOutcomeCount":outcome_count,"reference":reference_refs,"recent":recent_refs,
        "referenceSha256":canonical_sha256(reference_refs),"recentSha256":canonical_sha256(recent_refs),
        "combinedSelectionSha256":canonical_sha256({"reference":reference_refs,"recent":recent_refs}),
        "excludedPrefixCount":len(excluded_refs),"excludedPrefixSha256":canonical_sha256(excluded_refs),
        "warnings":period_warnings(ordered)}


def verify_disjoint_windows(reference: Sequence[Mapping[str, Any]], recent: Sequence[Mapping[str, Any]]) -> None:
    left = [str(value.get("outcomeId")) for value in reference]; right = [str(value.get("outcomeId")) for value in recent]
    if len(set(left)) != len(left) or len(set(right)) != len(right) or set(left) & set(right):
        raise ModelDegradationMetricError("Window outcome identities are not disjoint and unique.")


def aggregate_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = ordered_outcomes(records)
    if not values: raise ModelDegradationMetricError("At least one outcome is required.")
    residuals: list[float] = []; actuals: list[float] = []; percentages: list[float] = []; range_values: list[bool] = []
    for record in values:
        forecast = _finite(record.get("forecastRaw"), "forecastRaw"); observed = _finite(record.get("observedRaw"), "observedRaw")
        if observed < 0 or not observed.is_integer(): raise ModelDegradationMetricError("observedRaw must be a nonnegative integer.")
        residual = observed - forecast
        if not math.isfinite(residual): raise ModelDegradationMetricError("Residual must be finite.")
        residuals.append(residual); actuals.append(observed)
        if observed > 0: percentages.append(residual / observed * 100)
        coverage = record.get("coverageOutcome")
        if coverage in {"covered","lower_miss","upper_miss"}: range_values.append(coverage == "covered")
        elif coverage != "not_evaluable_no_empirical_range": raise ModelDegradationMetricError("Unknown range coverage status.")
    count = len(values); mae = math.fsum(abs(v) for v in residuals)/count; rmse = math.sqrt(math.fsum(v*v for v in residuals)/count); bias = math.fsum(residuals)/count
    result = {"count":count,"positiveActualCount":len(percentages),"zeroActualCount":count-len(percentages),"actualSum":math.fsum(actuals),"actualMean":math.fsum(actuals)/count,"actualMinimum":min(actuals),"actualMaximum":max(actuals),
        "mae":mae,"rmse":rmse,"signedBias":bias,"absoluteBias":abs(bias),"mpe":math.fsum(percentages)/len(percentages) if percentages else None,"mape":math.fsum(abs(v) for v in percentages)/len(percentages) if percentages else None,
        "percentageEligibleCount":len(percentages),"rangeEligibleCount":len(range_values),"empiricalCoverage":sum(range_values)/len(range_values) if range_values else None}
    canonical_json(result)
    return result


def metric_delta(reference: float, recent: float) -> float:
    return _finite(recent, "recent") - _finite(reference, "reference")


def metric_ratio(reference: float, recent: float) -> float | None:
    denominator = _finite(reference, "reference"); numerator = _finite(recent, "recent")
    return None if denominator == 0 else numerator / denominator


def training_history_context(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows: set[int] = set(); periods: set[str] = set(); matrices: set[str] = set(); assessments: set[str] = set(); decisions: set[str] = set()
    for record in records:
        evidence = record.get("sourceEvidence") if isinstance(record.get("sourceEvidence"), Mapping) else {}
        if isinstance(evidence.get("trainingRowCount"), int): rows.add(evidence["trainingRowCount"])
        if isinstance(evidence.get("trainingPeriod"), Mapping): periods.add(canonical_json(evidence["trainingPeriod"]))
        if isinstance(evidence.get("featureMatrixSha256"), str): matrices.add(evidence["featureMatrixSha256"])
        if isinstance(evidence.get("assessmentId"), str): assessments.add(evidence["assessmentId"])
        if isinstance(evidence.get("decisionId"), str): decisions.add(evidence["decisionId"])
    dimensions = (rows, periods, matrices, assessments, decisions)
    return {"trainingRowCounts":sorted(rows),"trainingPeriods":sorted(periods),"featureMatrixSha256s":sorted(matrices),"assessmentIds":sorted(assessments),"decisionIds":sorted(decisions),"variationRecorded":any(len(value)>1 for value in dimensions)}
