"""Side-effect-free P1.4G period, outcome, and monitoring mathematics."""
from __future__ import annotations
import hashlib, json, math, re, statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

PERIOD = re.compile(r"^(\d{4})-W(\d{2})$")

def parse_target_period(value: str) -> tuple[int, int]:
    match = PERIOD.fullmatch(str(value))
    if not match:
        raise ValueError("forecastTargetPeriod must use YYYY-Www.")
    year, week = map(int, match.groups())
    if week < 1 or week > 52:
        raise ValueError("forecastTargetPeriod uses an unsupported ISO week.")
    try:
        datetime.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise ValueError("forecastTargetPeriod is not a valid ISO period.") from exc
    return year, week

def calculate_period_completion(value: str, timezone_name: str = "Asia/Dhaka") -> datetime:
    year, week = parse_target_period(value)
    monday = datetime.fromisocalendar(year, week, 1).replace(tzinfo=ZoneInfo(timezone_name))
    return (monday + timedelta(weeks=1)).astimezone(timezone.utc)

def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite.")
    return number

def evaluate_outcome(forecast_raw: float, observed_raw: int, uncertainty: Mapping[str, Any]) -> dict[str, Any]:
    forecast = _finite(forecast_raw, "forecastRaw")
    if isinstance(observed_raw, bool) or not isinstance(observed_raw, int) or observed_raw < 0:
        raise ValueError("observedRaw must be a nonnegative integer.")
    signed = observed_raw - forecast
    absolute, squared = abs(signed), signed ** 2
    if not all(math.isfinite(v) for v in (signed, absolute, squared)):
        raise ValueError("Outcome errors must be finite.")
    percentage = signed / observed_raw * 100 if observed_raw > 0 else None
    result = {"signedError": signed, "errorDirection": "underforecast" if signed > 0 else "overforecast" if signed < 0 else "exact",
        "absoluteError": absolute, "squaredError": squared, "percentageError": percentage,
        "absolutePercentageError": abs(percentage) if percentage is not None else None,
        "percentageMetricStatus": "available" if percentage is not None else "not_evaluable_zero_observed"}
    status = uncertainty.get("uncertaintyStatus")
    if status == "available":
        lower, upper = _finite(uncertainty.get("lowerRaw"), "lowerRaw"), _finite(uncertainty.get("upperRaw"), "upperRaw")
        if lower < 0 or lower > upper:
            raise ValueError("Committed empirical range is invalid.")
        coverage = "lower_miss" if observed_raw < lower else "upper_miss" if observed_raw > upper else "covered"
        result.update(empiricalRangeStatus="available", lowerRaw=lower, upperRaw=upper,
                      coverageOutcome=coverage, intervalWidth=upper-lower)
    elif status == "pending_dataset_specific_calibration":
        if any(uncertainty.get(k) is not None for k in ("lowerRaw", "upperRaw")):
            raise ValueError("Pending empirical range contains bounds.")
        result.update(empiricalRangeStatus=status, lowerRaw=None, upperRaw=None,
                      coverageOutcome="not_evaluable_no_empirical_range", intervalWidth=None)
    else:
        raise ValueError("Unsupported committed uncertainty status.")
    return result

def deterministic_outcome_sort(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return sorted(records, key=lambda r: (str(r["forecastTargetPeriod"]), str(r["forecastRunId"]), str(r["outcomeId"])))

def deterministic_outcome_set_hash(records: Sequence[Mapping[str, Any]]) -> str:
    values = [{"outcomeId": r["outcomeId"], "outcomeEvidenceSha256": r["outcomeEvidenceSha256"]} for r in deterministic_outcome_sort(records)]
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()

def aggregate_outcomes(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = deterministic_outcome_sort(records)
    if not ordered:
        return {"evaluatedForecastCount":0,"cumulativeMAE":None,"cumulativeRMSE":None,"cumulativeBias":None,
            "cumulativeMPE":None,"cumulativeMAPE":None,"percentageMetricEvaluatedCount":0,"zeroObservedCount":0,
            "empiricalRangeEvaluatedCount":0,"empiricalRangeCoveredCount":0,"empiricalCoverage":None,
            "lowerMissCount":0,"upperMissCount":0,"earliestEvaluatedTargetPeriod":None,"latestEvaluatedTargetPeriod":None}
    n=len(ordered); valid=[r for r in ordered if r["percentageMetricStatus"]=="available"]
    ranged=[r for r in ordered if r["coverageOutcome"]!="not_evaluable_no_empirical_range"]
    covered=sum(r["coverageOutcome"]=="covered" for r in ranged)
    return {"evaluatedForecastCount":n,"cumulativeMAE":math.fsum(float(r["absoluteError"]) for r in ordered)/n,
        "cumulativeRMSE":math.sqrt(math.fsum(float(r["squaredError"]) for r in ordered)/n),
        "cumulativeBias":math.fsum(float(r["signedError"]) for r in ordered)/n,
        "cumulativeMPE":math.fsum(float(r["percentageError"]) for r in valid)/len(valid) if valid else None,
        "cumulativeMAPE":math.fsum(float(r["absolutePercentageError"]) for r in valid)/len(valid) if valid else None,
        "percentageMetricEvaluatedCount":len(valid),"zeroObservedCount":n-len(valid),
        "empiricalRangeEvaluatedCount":len(ranged),"empiricalRangeCoveredCount":covered,
        "empiricalCoverage":covered/len(ranged) if ranged else None,
        "lowerMissCount":sum(r["coverageOutcome"]=="lower_miss" for r in ranged),
        "upperMissCount":sum(r["coverageOutcome"]=="upper_miss" for r in ranged),
        "earliestEvaluatedTargetPeriod":ordered[0]["forecastTargetPeriod"],
        "latestEvaluatedTargetPeriod":ordered[-1]["forecastTargetPeriod"]}
