"""Deterministic, read-only portfolio benchmark mathematics."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
import statistics
from collections import Counter
from typing import Any, Iterable, Mapping, Sequence


SUCCESS = {"success", "warning"}
PROMINENT_PAIRS = {
    frozenset(pair)
    for pair in (
        ("random_forest", "extra_trees"),
        ("gradient_boosting", "hist_gradient_boosting"),
        ("ridge_regression", "elastic_net"),
        ("poisson_regression", "negative_binomial_regression"),
        ("poisson_regression", "poisson_gam"),
        ("poisson_gam", "random_forest"),
        ("poisson_gam", "extra_trees"),
        ("poisson_gam", "gradient_boosting"),
        ("poisson_gam", "hist_gradient_boosting"),
    )
}
TERTILE_LABELS = (
    "lower_observed_case_tertile",
    "middle_observed_case_tertile",
    "upper_observed_case_tertile",
)


class PortfolioBenchmarkEvidenceError(ValueError):
    """Raised when assessment evidence cannot support a deterministic benchmark."""


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _finite(values: Iterable[float]) -> list[float]:
    result = [float(value) for value in values]
    if not all(math.isfinite(value) for value in result):
        raise PortfolioBenchmarkEvidenceError("non_finite_metric_input")
    return result


def metric_summary(records: Sequence[Mapping[str, Any]], actuals: Sequence[float]) -> dict[str, Any]:
    if not records or len(records) != len(actuals):
        raise PortfolioBenchmarkEvidenceError("metric_cohort_mismatch")
    absolute = _finite(record["absoluteError"] for record in records)
    squared = _finite(record["squaredError"] for record in records)
    signed = _finite(record["signedError"] for record in records)
    runtimes = _finite(record["runtimeSeconds"] for record in records)
    observed = _finite(actuals)
    denominator = sum(observed)
    return {
        "mae": statistics.fmean(absolute),
        "rmse": math.sqrt(statistics.fmean(squared)),
        "wape": 100.0 * sum(absolute) / denominator if denominator else None,
        "medianAbsoluteError": statistics.median(absolute),
        "maximumAbsoluteError": max(absolute),
        "signedMeanError": statistics.fmean(signed),
        "successfulFoldCount": len(records),
        "totalRuntimeSeconds": sum(runtimes),
        "medianRuntimeSeconds": statistics.median(runtimes),
    }


def pearson(left: Sequence[float], right: Sequence[float]) -> dict[str, Any]:
    if len(left) != len(right) or len(left) < 2:
        return {"status": "insufficient_samples", "sampleCount": min(len(left), len(right)), "value": None}
    try:
        x, y = _finite(left), _finite(right)
    except PortfolioBenchmarkEvidenceError:
        return {"status": "non_finite_input", "sampleCount": len(left), "value": None}
    mean_x, mean_y = statistics.fmean(x), statistics.fmean(y)
    centered_x = [value - mean_x for value in x]
    centered_y = [value - mean_y for value in y]
    scale_x = math.sqrt(sum(value * value for value in centered_x))
    scale_y = math.sqrt(sum(value * value for value in centered_y))
    if scale_x == 0.0 or scale_y == 0.0:
        return {"status": "constant_series", "sampleCount": len(x), "value": None}
    value = sum(a * b for a, b in zip(centered_x, centered_y)) / (scale_x * scale_y)
    return {"status": "computable", "sampleCount": len(x), "value": max(-1.0, min(1.0, value))}


def _sizes(total: int, groups: int) -> list[int]:
    quotient, remainder = divmod(total, groups)
    return [quotient + (1 if index < remainder else 0) for index in range(groups)]


def _prediction_map(fold: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    predictions = fold["predictions"]
    result = {str(record["modelId"]): record for record in predictions}
    if len(result) != len(predictions):
        raise PortfolioBenchmarkEvidenceError("duplicate_candidate_prediction")
    return result


def _successful(record: Mapping[str, Any]) -> bool:
    return record.get("foldStatus") in SUCCESS


def _records(
    folds: Sequence[Mapping[str, Any]], model_id: str
) -> tuple[list[Mapping[str, Any]], list[float]]:
    records, actuals = [], []
    for fold in folds:
        record = _prediction_map(fold)[model_id]
        if not _successful(record):
            raise PortfolioBenchmarkEvidenceError("non_success_record_in_metric_cohort")
        records.append(record)
        actuals.append(float(fold["actualTarget"]))
    return records, actuals


def _metrics_for(folds: Sequence[Mapping[str, Any]], model_id: str) -> dict[str, Any]:
    records, actuals = _records(folds, model_id)
    return metric_summary(records, actuals)


def _rank(
    folds: Sequence[Mapping[str, Any]],
    candidate_order: Sequence[str],
    tolerance: float,
) -> list[str]:
    if not folds:
        return []
    order = {model_id: index for index, model_id in enumerate(candidate_order)}
    values = [(model_id, _metrics_for(folds, model_id)) for model_id in candidate_order]
    return [
        model_id
        for model_id, _ in sorted(
            values,
            key=lambda item: (
                item[1]["mae"],
                item[1]["rmse"],
                math.inf if item[1]["wape"] is None else item[1]["wape"],
                item[1]["medianAbsoluteError"],
                item[1]["maximumAbsoluteError"],
                order[item[0]],
            ),
        )
    ]


def _fold_win_summary(
    folds: Sequence[Mapping[str, Any]], candidate_order: Sequence[str], tolerance: float
) -> list[dict[str, Any]]:
    counts = {model_id: {"outrightWins": 0, "tiedWins": 0, "losses": 0} for model_id in candidate_order}
    for fold in folds:
        predictions = _prediction_map(fold)
        errors = {model_id: float(predictions[model_id]["absoluteError"]) for model_id in candidate_order}
        best = min(errors.values())
        winners = [model_id for model_id in candidate_order if abs(errors[model_id] - best) <= tolerance]
        for model_id in candidate_order:
            if model_id in winners:
                counts[model_id]["tiedWins" if len(winners) > 1 else "outrightWins"] += 1
            else:
                counts[model_id]["losses"] += 1
    available = len(folds)
    return [
        {
            "modelId": model_id,
            **counts[model_id],
            "availableFolds": available,
            "winShare": counts[model_id]["outrightWins"] / available if available else None,
            "tieShare": counts[model_id]["tiedWins"] / available if available else None,
        }
        for model_id in candidate_order
    ]


def descriptive_tertiles(folds: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(folds, key=lambda fold: (float(fold["actualTarget"]), int(fold["sequence"])))
    result, offset = [], 0
    for label, size in zip(TERTILE_LABELS, _sizes(len(ordered), 3)):
        group = ordered[offset : offset + size]
        offset += size
        result.append(
            {
                "label": label,
                "foldIds": [str(fold["foldId"]) for fold in group],
                "foldCount": len(group),
                "minimumActualTarget": min((float(fold["actualTarget"]) for fold in group), default=None),
                "maximumActualTarget": max((float(fold["actualTarget"]) for fold in group), default=None),
                "operationalThreshold": False,
            }
        )
    return result


def _metric_delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mae": left["mae"] - right["mae"],
        "rmse": left["rmse"] - right["rmse"],
        "wape": None if left["wape"] is None or right["wape"] is None else left["wape"] - right["wape"],
    }


def _better_tied_worse(
    folds: Sequence[Mapping[str, Any]], left_id: str, right_id: str, tolerance: float
) -> dict[str, int]:
    better = tied = worse = 0
    for fold in folds:
        predictions = _prediction_map(fold)
        difference = float(predictions[left_id]["absoluteError"]) - float(predictions[right_id]["absoluteError"])
        if difference < -tolerance:
            better += 1
        elif abs(difference) <= tolerance:
            tied += 1
        else:
            worse += 1
    return {"leftBetter": better, "tied": tied, "leftWorse": worse}


def _failure_summary(folds: Sequence[Mapping[str, Any]], model_id: str) -> dict[str, Any]:
    records = [_prediction_map(fold)[model_id] for fold in folds]
    failures = [record for record in records if not _successful(record)]
    return {
        "failedFoldCount": len(failures),
        "reasonFrequency": [
            {"reason": reason, "count": count}
            for reason, count in sorted(Counter(str(record["failureReasonCode"]) for record in failures).items())
        ],
        "totalRuntimeSeconds": sum(float(record["runtimeSeconds"]) for record in records),
    }


def _pairwise(
    folds: Sequence[Mapping[str, Any]],
    left_id: str,
    right_id: str,
    candidate_metadata: Mapping[str, Mapping[str, Any]],
    tolerance: float,
    tertile_by_fold: Mapping[str, str],
) -> dict[str, Any]:
    pair_folds = [
        fold
        for fold in folds
        if _successful(_prediction_map(fold)[left_id]) and _successful(_prediction_map(fold)[right_id])
    ]
    left_metrics = _metrics_for(pair_folds, left_id) if pair_folds else None
    right_metrics = _metrics_for(pair_folds, right_id) if pair_folds else None
    left_records, _ = _records(pair_folds, left_id) if pair_folds else ([], [])
    right_records, _ = _records(pair_folds, right_id) if pair_folds else ([], [])
    midpoint = (len(pair_folds) + 1) // 2
    halves = []
    for label, group in (("first_half", pair_folds[:midpoint]), ("second_half", pair_folds[midpoint:])):
        halves.append(
            {
                "label": label,
                "foldIds": [str(fold["foldId"]) for fold in group],
                "metricDelta": _metric_delta(_metrics_for(group, left_id), _metrics_for(group, right_id)) if group else None,
            }
        )
    strata = []
    for label in TERTILE_LABELS:
        group = [fold for fold in pair_folds if tertile_by_fold.get(str(fold["foldId"])) == label]
        strata.append(
            {
                "label": label,
                "foldIds": [str(fold["foldId"]) for fold in group],
                "metricDelta": _metric_delta(_metrics_for(group, left_id), _metrics_for(group, right_id)) if group else None,
            }
        )
    return {
        "leftModelId": left_id,
        "rightModelId": right_id,
        "prominent": frozenset((left_id, right_id)) in PROMINENT_PAIRS,
        "commonSuccessfulFoldIds": [str(fold["foldId"]) for fold in pair_folds],
        "sampleCount": len(pair_folds),
        "leftMetrics": left_metrics,
        "rightMetrics": right_metrics,
        "metricDeltaLeftMinusRight": _metric_delta(left_metrics, right_metrics) if pair_folds else None,
        "absoluteErrorComparison": _better_tied_worse(pair_folds, left_id, right_id, tolerance),
        "signedResidualCorrelation": pearson(
            [float(record["signedError"]) for record in left_records],
            [float(record["signedError"]) for record in right_records],
        ),
        "absoluteErrorCorrelation": pearson(
            [float(record["absoluteError"]) for record in left_records],
            [float(record["absoluteError"]) for record in right_records],
        ),
        "predictionCorrelation": pearson(
            [float(record["publishedPrediction"]) for record in left_records],
            [float(record["publishedPrediction"]) for record in right_records],
        ),
        "halfDeltas": halves,
        "descriptiveTertileDeltas": strata,
        "leftFailureSummary": _failure_summary(folds, left_id),
        "rightFailureSummary": _failure_summary(folds, right_id),
        "leftModelFamily": candidate_metadata[left_id]["modelFamily"],
        "rightModelFamily": candidate_metadata[right_id]["modelFamily"],
        "leftPreprocessingIdentity": candidate_metadata[left_id]["preprocessingIdentity"],
        "rightPreprocessingIdentity": candidate_metadata[right_id]["preprocessingIdentity"],
    }


def build_benchmark(
    *,
    benchmark_id: str,
    generated_at: str,
    evidence_scope: str,
    policy_identity: Mapping[str, str],
    source: Mapping[str, Any],
    candidate_order: Sequence[str],
    candidate_registry_version: str,
    candidate_registry_sha256: str,
    assessment_policy_identity: Mapping[str, str],
    tolerance: float,
) -> dict[str, Any]:
    rolling = source["rolling"]
    comparison = source["comparison"]
    folds = list(rolling["folds"])
    fold_ids = [str(fold["foldId"]) for fold in folds]
    if len(set(fold_ids)) != len(fold_ids):
        raise PortfolioBenchmarkEvidenceError("duplicate_fold")
    if list(rolling["candidateIds"]) != list(candidate_order):
        raise PortfolioBenchmarkEvidenceError("wrong_candidate_order")
    for fold in folds:
        predictions = _prediction_map(fold)
        if list(predictions) != list(candidate_order):
            raise PortfolioBenchmarkEvidenceError("wrong_prediction_candidate_order")

    common = [
        fold
        for fold in folds
        if all(_successful(_prediction_map(fold)[model_id]) for model_id in candidate_order)
    ]
    common_ids = [str(fold["foldId"]) for fold in common]
    excluded = []
    for fold in folds:
        failures = [
            {
                "modelId": model_id,
                "foldStatus": _prediction_map(fold)[model_id]["foldStatus"],
                "failureReasonCode": _prediction_map(fold)[model_id]["failureReasonCode"],
            }
            for model_id in candidate_order
            if not _successful(_prediction_map(fold)[model_id])
        ]
        if failures:
            excluded.append({"foldId": str(fold["foldId"]), "reasons": failures})
    source_candidates = {str(candidate["modelId"]): candidate for candidate in comparison["candidates"]}
    candidate_summaries = []
    for model_id in candidate_order:
        records = [_prediction_map(fold)[model_id] for fold in folds]
        successful = [record for record in records if _successful(record)]
        candidate = source_candidates[model_id]
        candidate_summaries.append(
            {
                "modelId": model_id,
                "candidateClass": candidate["candidateClass"],
                "deployabilityClass": candidate["deployabilityClass"],
                "modelFamily": candidate["modelFamily"],
                "preprocessingIdentity": candidate["preprocessingIdentity"],
                "plannedFolds": len(folds),
                "successfulFolds": len(successful),
                "failedFolds": len(folds) - len(successful),
                "completionRate": len(successful) / len(folds) if folds else 0.0,
                "failureReasonFrequency": _failure_summary(folds, model_id)["reasonFrequency"],
                "sourceReportedAssessmentMetrics": candidate["metrics"],
                "candidateSpecificCohortLabel": "non_comparable_candidate_specific_cohort",
                "primaryCommonCohortMetrics": _metrics_for(common, model_id) if common else None,
            }
        )
    tertiles = descriptive_tertiles(common)
    tertile_by_fold = {
        fold_id: str(group["label"]) for group in tertiles for fold_id in group["foldIds"]
    }
    pairs = [
        _pairwise(folds, left, right, source_candidates, tolerance, tertile_by_fold)
        for left, right in itertools.combinations(candidate_order, 2)
    ]
    baseline_ids = [
        model_id for model_id in candidate_order if source_candidates[model_id]["candidateClass"] == "comparison_baseline"
    ]
    learned_ids = [model_id for model_id in candidate_order if model_id not in baseline_ids]
    baseline_relative = []
    for model_id in learned_ids:
        for baseline_id in baseline_ids:
            model_metrics, baseline_metrics = _metrics_for(common, model_id), _metrics_for(common, baseline_id)
            baseline_relative.append(
                {
                    "modelId": model_id,
                    "baselineModelId": baseline_id,
                    "metricDeltaModelMinusBaseline": _metric_delta(model_metrics, baseline_metrics),
                    "absoluteErrorComparison": _better_tied_worse(common, model_id, baseline_id, tolerance),
                }
            )
    midpoint = (len(common) + 1) // 2
    half_groups = (("first_half", common[:midpoint]), ("second_half", common[midpoint:]))
    blocks, offset = [], 0
    for index, size in enumerate(_sizes(len(common), 3), start=1):
        group = common[offset : offset + size]
        offset += size
        blocks.append(
            {"label": f"contiguous_block_{index}", "foldIds": [str(fold["foldId"]) for fold in group], "ranking": _rank(group, candidate_order, tolerance)}
        )
    per_fold_rank = {model_id: Counter() for model_id in candidate_order}
    for fold in common:
        predictions = _prediction_map(fold)
        ordered_errors = sorted(
            ((model_id, float(predictions[model_id]["absoluteError"])) for model_id in candidate_order),
            key=lambda item: (item[1], candidate_order.index(item[0])),
        )
        previous = None
        rank = 0
        for index, (model_id, error) in enumerate(ordered_errors, start=1):
            if previous is None or abs(error - previous) > tolerance:
                rank = index
            per_fold_rank[model_id][rank] += 1
            previous = error
    technical_winner = str(comparison["technicalWinnerModelId"])
    rationalization = []
    for candidate in candidate_summaries:
        model_id = candidate["modelId"]
        if candidate["candidateClass"] == "comparison_baseline" or model_id == technical_winner:
            category = "KEEP_CORE"
        elif candidate["failedFolds"]:
            category = "KEEP_PENDING_MORE_DATA"
        else:
            category = "INSUFFICIENT_EVIDENCE"
        rationalization.append(
            {
                "modelId": model_id,
                "category": category,
                "advisory": True,
                "reasonCodes": (
                    ["required_comparison_baseline"]
                    if candidate["candidateClass"] == "comparison_baseline"
                    else ["source_technical_winner_retained"]
                    if model_id == technical_winner
                    else ["incomplete_source_fold_completion", "single_synthetic_assessment"]
                    if candidate["failedFolds"]
                    else ["single_synthetic_assessment", "redundancy_and_retirement_thresholds_not_governed"]
                ),
            }
        )
    limitations = [
        "This artifact is production system qualification evidence, not real-world Dhaka calibration or operational Dhaka accuracy validation.",
        "One assessment is not broad field validation.",
        "Descriptive observed-case tertiles are not outbreak or operational thresholds.",
        "Runtime evidence is descriptive evidence from one run and machine.",
        "The common cohort may be reduced by candidate failures.",
        "No automatic model-removal authority exists; all rationalization results are advisory.",
        "Synthetic qualification cannot establish clinical, hospital-approved, or operational Dhaka performance.",
    ]
    return {
        "schemaVersion": "1.0",
        "benchmarkId": benchmark_id,
        "generatedAt": generated_at,
        "evidenceScope": evidence_scope,
        "operationalDhakaValidation": evidence_scope in {"historical_dhaka", "real_dhaka"},
        "datasetSourceClassification": "synthetic_benchmark" if evidence_scope == "synthetic_qualification" else evidence_scope,
        "policy": dict(policy_identity),
        "sourceAuthority": {
            "assessmentId": rolling["assessmentId"],
            "assessmentPath": source["assessmentPath"],
            "assessmentCommitSha256": source["assessmentCommitSha256"],
            "datasetId": rolling["datasetId"],
            "validationRecordSha256": source["commit"]["validationRecordSha256"],
            "assessmentPolicy": dict(assessment_policy_identity),
            "candidateRegistryVersion": candidate_registry_version,
            "candidateRegistrySha256": candidate_registry_sha256,
            "foldPlanSha256": rolling["foldPlanSha256"],
            "target": rolling["target"],
            "horizonWeeks": rolling["horizonWeeks"],
        },
        "candidateOrder": list(candidate_order),
        "sourceFoldCounts": {
            "plannedFolds": int(rolling["plannedFoldCount"]),
            "candidateCompletion": [
                {
                    "modelId": candidate["modelId"],
                    "successfulFolds": candidate["successfulFolds"],
                    "failedFolds": candidate["failedFolds"],
                }
                for candidate in candidate_summaries
            ],
        },
        "primaryCohort": {
            "method": "intersection_of_successful_or_warning_folds_for_every_candidate",
            "commonSuccessFoldCount": len(common),
            "orderedCommonFoldIds": common_ids,
            "commonFoldSetSha256": canonical_sha256(common_ids),
            "excludedFolds": excluded,
        },
        "candidateSummaries": candidate_summaries,
        "baselineRelativeSummaries": baseline_relative,
        "foldWinSummaries": _fold_win_summary(common, candidate_order, tolerance),
        "pairwiseComparisons": pairs,
        "descriptiveObservedCaseTertiles": tertiles,
        "rankingStability": {
            "firstSecondHalf": [
                {"label": label, "foldIds": [str(fold["foldId"]) for fold in group], "ranking": _rank(group, candidate_order, tolerance)}
                for label, group in half_groups
            ],
            "contiguousBlocks": blocks,
            "descriptiveTertiles": [
                {
                    "label": tertile["label"],
                    "foldIds": tertile["foldIds"],
                    "ranking": _rank(
                        [fold for fold in common if str(fold["foldId"]) in set(tertile["foldIds"])],
                        candidate_order,
                        tolerance,
                    ),
                }
                for tertile in tertiles
            ],
            "perFoldRankDistributions": [
                {
                    "modelId": model_id,
                    "rankCounts": [
                        {"rank": rank, "count": count}
                        for rank, count in sorted(per_fold_rank[model_id].items())
                    ],
                }
                for model_id in candidate_order
            ],
        },
        "sourceTechnicalWinnerModelId": technical_winner,
        "rationalization": {
            "advisoryOnly": True,
            "redundancyClassificationStatus": "not_governed",
            "retirementThresholdStatus": "not_governed",
            "recommendations": rationalization,
            "automaticCandidateRemovalAllowed": False,
            "automaticRegistryMutationAllowed": False,
            "automaticAssignmentMutationAllowed": False,
            "automaticPolicyMutationAllowed": False,
        },
        "limitations": limitations,
    }
