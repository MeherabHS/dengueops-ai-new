"""Deterministic B9.D drift, recommendation, and forecast-evidence confidence."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

from jsonschema import Draft202012Validator

from runtime_context import ROOT


POLICY_ID = "RUNTIME.MODEL_DEGRADATION.EVIDENCE"
POLICY_VERSION = "b9.d-v1"
POLICY_SHA = "3ebf8c09d8ffa45ad6c46462580796969d80b782da8c255fac027395b1c80172"
POLICY_PATH = ROOT / "config/deployments/dhaka_south/model_monitoring_policy.json"
POLICY_SCHEMA_PATH = ROOT / "config/model_monitoring_policy.schema.json"


class GovernedMonitoringError(ValueError):
    """Raised when governed monitoring inputs or policy evidence fail closed."""


def canonical_sha256(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    content = dict(value)
    if omit is not None:
        content.pop(omit, None)
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_monitoring_policy(policy: Mapping[str, Any], expected_sha256: str | None = None) -> str:
    try:
        schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernedMonitoringError("Monitoring policy schema is unavailable.") from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(policy), key=lambda item: list(item.path))
    digest = canonical_sha256(policy, omit="policy_sha256")
    weights = policy.get("confidence", {}).get("weights", {})
    if errors or digest != policy.get("policy_sha256") or expected_sha256 not in (None, digest):
        raise GovernedMonitoringError("Monitoring policy schema or hash is invalid.")
    if not math.isclose(sum(float(value) for value in weights.values()), 1.0, rel_tol=0, abs_tol=1e-12):
        raise GovernedMonitoringError("Confidence policy weights must sum to 1.0.")
    calibration_weights = policy.get("confidence", {}).get("calibration_component_weights", {})
    if not math.isclose(sum(float(value) for value in calibration_weights.values()), 1.0, rel_tol=0, abs_tol=1e-12):
        raise GovernedMonitoringError("Calibration component weights must sum to 1.0.")
    feature = policy["feature_drift"]
    performance = policy["performance_drift"]
    bands = policy["confidence"]["bands"]
    if not (0 <= feature["warning_threshold"] < feature["material_threshold"]):
        raise GovernedMonitoringError("Feature-drift thresholds are invalid.")
    if not (1 < performance["warning_ratio"] < performance["material_ratio"]):
        raise GovernedMonitoringError("Performance-drift thresholds are invalid.")
    if not (0 <= bands["moderate_minimum"] < bands["high_minimum"] <= 1):
        raise GovernedMonitoringError("Confidence bands are invalid.")
    return digest


def load_monitoring_policy(expected_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    try:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GovernedMonitoringError("Monitoring policy is unavailable.") from exc
    digest = validate_monitoring_policy(policy, expected_sha256)
    if (policy.get("policy_id"), policy.get("policy_version"), digest) != (POLICY_ID, POLICY_VERSION, POLICY_SHA):
        raise GovernedMonitoringError("Monitoring policy identity is invalid.")
    return policy, digest


def _finite(values: Sequence[float], label: str) -> list[float]:
    result = [float(value) for value in values]
    if not result or any(not math.isfinite(value) for value in result):
        raise GovernedMonitoringError(f"{label} must contain finite observations.")
    return result


def _quantile(ordered: Sequence[float], probability: float) -> float:
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(ordered[lower] + fraction * (ordered[upper] - ordered[lower]))


def reference_quantile_boundaries(reference: Sequence[float], maximum_bin_count: int) -> list[float]:
    values = sorted(_finite(reference, "Reference distribution"))
    if maximum_bin_count < 2:
        raise GovernedMonitoringError("At least two requested bins are required.")
    candidates = [_quantile(values, index / maximum_bin_count) for index in range(1, maximum_bin_count)]
    boundaries: list[float] = []
    for value in candidates:
        if not boundaries or value > boundaries[-1]:
            boundaries.append(value)
    return boundaries


def population_stability_index(
    reference: Sequence[float], current: Sequence[float], *, maximum_bin_count: int, epsilon: float,
) -> dict[str, Any]:
    reference_values = _finite(reference, "Reference distribution")
    current_values = _finite(current, "Current distribution")
    if not 0 < epsilon <= 0.01:
        raise GovernedMonitoringError("PSI epsilon is outside its governed bound.")
    boundaries = reference_quantile_boundaries(reference_values, maximum_bin_count)
    bin_count = len(boundaries) + 1
    reference_counts = [0] * bin_count
    current_counts = [0] * bin_count
    for value in reference_values:
        reference_counts[bisect.bisect_right(boundaries, value)] += 1
    for value in current_values:
        current_counts[bisect.bisect_right(boundaries, value)] += 1
    terms = []
    for reference_count, current_count in zip(reference_counts, current_counts):
        reference_share = max(reference_count / len(reference_values), epsilon)
        current_share = max(current_count / len(current_values), epsilon)
        terms.append((current_share - reference_share) * math.log(current_share / reference_share))
    value = math.fsum(terms)
    if not math.isfinite(value) or value < 0:
        raise GovernedMonitoringError("PSI calculation produced invalid evidence.")
    return {
        "metric": "population_stability_index", "value": value,
        "referenceBoundaries": boundaries, "effectiveBinCount": bin_count,
        "referenceCounts": reference_counts, "currentCounts": current_counts,
    }


def evaluate_feature_drift(
    reference_rows: Sequence[Mapping[str, Any]], current_rows: Sequence[Mapping[str, Any]],
    feature_ids: Sequence[str], policy: Mapping[str, Any], *, feature_authority_compatible: bool = True,
) -> dict[str, Any]:
    governed = policy["feature_drift"]
    minimum = int(governed["minimum_observations"])
    window_size = int(governed["current_window_rows"])
    if not feature_authority_compatible:
        return {"status": "incompatible_feature_authority", "aggregateStatus": "incompatible", "perFeature": [],
            "referenceObservationCount": len(reference_rows), "currentObservationCount": len(current_rows), "currentWindowRows": window_size,
            "maximumValue": None, "warningFeatureCount": 0, "materialFeatureCount": 0, "warningShare": None}
    if len(reference_rows) < minimum or len(current_rows) < minimum:
        return {"status": "insufficient_monitoring_history", "aggregateStatus": "insufficient_data", "perFeature": [],
            "referenceObservationCount": len(reference_rows), "currentObservationCount": len(current_rows), "currentWindowRows": window_size,
            "maximumValue": None, "warningFeatureCount": 0, "materialFeatureCount": 0, "warningShare": None}
    current_window = list(current_rows)[-window_size:]
    warning = float(governed["warning_threshold"])
    material = float(governed["material_threshold"])
    features = []
    for feature_id in feature_ids:
        if any(feature_id not in row for row in reference_rows) or any(feature_id not in row for row in current_window):
            raise GovernedMonitoringError("A governed predictive feature is missing.")
        metric = population_stability_index(
            [float(row[feature_id]) for row in reference_rows], [float(row[feature_id]) for row in current_window],
            maximum_bin_count=int(governed["maximum_bin_count"]), epsilon=float(governed["zero_proportion_epsilon"]),
        )
        status = "material_drift" if metric["value"] >= material else "watch" if metric["value"] >= warning else "stable"
        features.append({"featureId": feature_id, **metric, "status": status})
    maximum = max(item["value"] for item in features)
    warning_count = sum(item["status"] in {"watch", "material_drift"} for item in features)
    material_count = sum(item["status"] == "material_drift" for item in features)
    warning_share = warning_count / len(features)
    aggregation = governed["aggregation"]
    if material_count >= int(aggregation["material_feature_count"]):
        aggregate = "material_drift"
    elif warning_count and (maximum >= warning or warning_share >= float(aggregation["warning_share"])):
        aggregate = "watch"
    else:
        aggregate = "stable"
    return {"status": aggregate, "aggregateStatus": aggregate, "perFeature": features,
        "referenceObservationCount": len(reference_rows), "currentObservationCount": len(current_window), "currentWindowRows": window_size,
        "maximumValue": maximum, "warningFeatureCount": warning_count, "materialFeatureCount": material_count, "warningShare": warning_share}


def evaluate_performance_drift(
    pairs: Sequence[Mapping[str, Any]], baseline: Mapping[str, float], policy: Mapping[str, Any],
) -> dict[str, Any]:
    governed = policy["performance_drift"]
    mature = [pair for pair in pairs if pair.get("mature") is True]
    if any(pair.get("identityValid") is not True for pair in mature):
        return {"status": "identity_mismatch", "matureOutcomeCount": 0, "metrics": None, "referenceMetrics": dict(baseline), "ratios": None}
    if not mature:
        return {"status": "awaiting_outcomes", "matureOutcomeCount": 0, "metrics": None, "referenceMetrics": dict(baseline), "ratios": None}
    if len(mature) < int(governed["minimum_mature_outcomes"]):
        return {"status": "insufficient_outcomes", "matureOutcomeCount": len(mature), "metrics": None, "referenceMetrics": dict(baseline), "ratios": None}
    residuals = [float(pair["actualOutcome"]) - float(pair["pointForecast"]) for pair in mature]
    actuals = [float(pair["actualOutcome"]) for pair in mature]
    if any(not math.isfinite(value) for value in residuals + actuals) or any(value < 0 for value in actuals):
        raise GovernedMonitoringError("Mature outcome evidence is numerically invalid.")
    metrics = {"mae": statistics.mean(abs(value) for value in residuals),
        "rmse": math.sqrt(statistics.mean(value * value for value in residuals)),
        "wape": 100 * math.fsum(abs(value) for value in residuals) / math.fsum(actuals) if math.fsum(actuals) > 0 else None}
    ratios: dict[str, float | None] = {}
    for metric in governed["metrics"]:
        reference = baseline.get(metric)
        observed = metrics.get(metric)
        ratios[metric] = None if reference is None or float(reference) <= 0 or observed is None else float(observed) / float(reference)
    comparable = [value for value in ratios.values() if value is not None]
    if not comparable:
        return {"status": "reference_unavailable", "matureOutcomeCount": len(mature), "metrics": metrics, "referenceMetrics": dict(baseline), "ratios": ratios}
    maximum = max(comparable)
    status = "material_degradation" if maximum >= float(governed["material_ratio"]) else "watch" if maximum >= float(governed["warning_ratio"]) else "stable"
    return {"status": status, "matureOutcomeCount": len(mature), "metrics": metrics, "referenceMetrics": dict(baseline), "ratios": ratios, "maximumDegradationRatio": maximum}


def evaluate_ranking_instability(
    source_winner: str | None, latest_winner: str | None, assigned_candidate: str,
    source_ranking: Sequence[str], latest_ranking: Sequence[str] | None,
) -> dict[str, Any]:
    if latest_ranking is None:
        return {"status": "no_new_reassessment", "winnerChanged": False, "sourceTechnicalWinnerId": source_winner,
            "latestTechnicalWinnerId": None, "previousAssignedCandidateRank": _rank(source_ranking, assigned_candidate),
            "latestAssignedCandidateRank": None, "rankDelta": None, "candidateEligibilityChanged": False}
    previous_rank = _rank(source_ranking, assigned_candidate)
    latest_rank = _rank(latest_ranking, assigned_candidate)
    return {"status": "technical_winner_changed" if source_winner != latest_winner else "stable",
        "winnerChanged": source_winner != latest_winner, "sourceTechnicalWinnerId": source_winner,
        "latestTechnicalWinnerId": latest_winner, "previousAssignedCandidateRank": previous_rank,
        "latestAssignedCandidateRank": latest_rank, "rankDelta": None if previous_rank is None or latest_rank is None else previous_rank - latest_rank,
        "candidateEligibilityChanged": (previous_rank is None) != (latest_rank is None)}


def _rank(ranking: Sequence[str], candidate_id: str) -> int | None:
    try:
        return list(ranking).index(candidate_id) + 1
    except ValueError:
        return None


def reassessment_recommendation(feature: Mapping[str, Any], performance: Mapping[str, Any], ranking: Mapping[str, Any]) -> dict[str, Any]:
    reasons = []
    if feature.get("status") == "incompatible_feature_authority": reasons.append("incompatible_feature_authority")
    if ranking.get("winnerChanged") is True: reasons.append("technical_winner_changed")
    if reasons:
        state = "review_required"
    elif feature.get("status") == "material_drift":
        state, reasons = "recommended", ["material_input_drift"]
    elif performance.get("status") == "material_degradation":
        state, reasons = "recommended", ["material_performance_degradation"]
    elif feature.get("status") == "watch" or performance.get("status") == "watch":
        state, reasons = "monitor", ["watch_evidence"]
    else:
        state = "not_recommended"
    return {"state": state, "reasonCodes": reasons, "actionHref": "/forecast?intent=reassess",
        "automaticReassessmentStarted": False, "automaticAssignmentAllowed": False}


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def calculate_confidence(
    *, calibration: Mapping[str, Any], interval: Mapping[str, Any], feature_drift: Mapping[str, Any],
    data_quality: Mapping[str, Any], performance: Mapping[str, Any], policy: Mapping[str, Any],
) -> dict[str, Any]:
    governed = policy["confidence"]
    if calibration.get("status") != "governed_available" or interval.get("status") != "governed_available":
        return {"status": "unavailable", "classification": "forecast_evidence_confidence", "rawNormalizedScore": None,
            "score": None, "band": None, "components": {}, "appliedWeights": {},
            "reasonCodes": [str(calibration.get("reason") or "prediction_interval_unavailable")]}
    if feature_drift.get("status") == "incompatible_feature_authority" or data_quality.get("verified") is not True:
        reason = "incompatible_feature_authority" if feature_drift.get("status") == "incompatible_feature_authority" else "data_quality_authority_unverified"
        return {"status": "unavailable", "classification": "forecast_evidence_confidence", "rawNormalizedScore": None,
            "score": None, "band": None, "components": {}, "appliedWeights": {}, "reasonCodes": [reason]}
    sample_count = int(calibration.get("sampleCount", 0)); minimum = int(calibration.get("minimumRequired", 1))
    historical = float(calibration.get("historicalCoverage", 0)); nominal = float(calibration.get("nominalCoverage", 0))
    sample_score = _clamp(sample_count / max(minimum, 1))
    coverage_score = _clamp(1 - abs(historical - nominal) / float(governed["calibration_coverage_tolerance"]))
    calibration_weights = governed["calibration_component_weights"]
    calibration_score = _clamp(float(calibration_weights["sample_sufficiency"]) * sample_score
        + float(calibration_weights["coverage_alignment"]) * coverage_score)
    width = float(interval["upperRaw"]) - float(interval["lowerRaw"])
    scale = float(interval["referenceOutcomeScale"])
    if not math.isfinite(width) or width < 0 or not math.isfinite(scale) or scale <= 0:
        raise GovernedMonitoringError("Interval precision evidence is invalid.")
    width_ratio = width / scale
    precision_score = _clamp(1 - width_ratio / float(governed["interval_width_ratio_at_zero"]))
    maximum_psi = feature_drift.get("maximumValue")
    if maximum_psi is None:
        raise GovernedMonitoringError("Input-stability evidence is unavailable.")
    material = float(policy["feature_drift"]["material_threshold"])
    input_score = _clamp(1 - float(maximum_psi) / material)
    data_score = _clamp(float(data_quality.get("score", 0)))
    components: dict[str, float] = {"calibrationEvidenceScore": calibration_score,
        "intervalPrecisionScore": precision_score, "inputStabilityScore": input_score, "dataQualityScore": data_score}
    if performance.get("status") in {"stable", "watch", "material_degradation"}:
        ratio = float(performance.get("maximumDegradationRatio", 1))
        material_ratio = float(policy["performance_drift"]["material_ratio"])
        components["performanceScore"] = _clamp(1 - max(0.0, ratio - 1.0) / max(material_ratio - 1.0, 1e-12))
    weights = governed["weights"]
    denominator = math.fsum(float(weights[name]) for name in components)
    if denominator <= 0:
        raise GovernedMonitoringError("No governed confidence weight is available.")
    applied = {name: float(weights[name]) / denominator for name in components}
    raw = _clamp(math.fsum(components[name] * applied[name] for name in components))
    score = int((Decimal(str(raw * 100))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    bands = governed["bands"]
    band = "high" if raw >= float(bands["high_minimum"]) else "moderate" if raw >= float(bands["moderate_minimum"]) else "low"
    return {"status": "available", "classification": "forecast_evidence_confidence", "rawNormalizedScore": raw,
        "score": score, "band": band, "components": components, "appliedWeights": applied,
        "reasonCodes": []}
