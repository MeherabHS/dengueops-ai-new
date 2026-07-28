from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from portfolio_benchmark_evidence import (
    PortfolioBenchmarkEvidenceError,
    build_benchmark,
    descriptive_tertiles,
    metric_summary,
    pearson,
)


IDS = ("moving_average_4w", "ridge_regression", "negative_binomial_regression")
SHA = "1" * 64


def prediction(model_id: str, actual: float, predicted: float | None, runtime: float = 1.0):
    if predicted is None:
        return {
            "modelId": model_id, "foldStatus": "failed", "rawPrediction": None,
            "publishedPrediction": None, "clippingApplied": False, "signedError": None,
            "absoluteError": None, "squaredError": None,
            "failureReasonCode": "convergence_failure", "warningCodes": [],
            "runtimeSeconds": runtime,
        }
    signed = predicted - actual
    return {
        "modelId": model_id, "foldStatus": "success", "rawPrediction": predicted,
        "publishedPrediction": predicted, "clippingApplied": False, "signedError": signed,
        "absoluteError": abs(signed), "squaredError": signed * signed,
        "failureReasonCode": None, "warningCodes": [], "runtimeSeconds": runtime,
    }


def source_fixture():
    actuals = (10.0, 20.0, 30.0, 40.0, 50.0, 60.0)
    folds = []
    for index, actual in enumerate(actuals, start=1):
        folds.append({
            "foldId": f"fold-{index}", "sequence": index, "actualTarget": actual,
            "predictions": [
                prediction(IDS[0], actual, actual + (3 if index % 2 else -3), 0.1),
                prediction(IDS[1], actual, actual + (1 if index % 2 else -2), 0.2),
                prediction(IDS[2], actual, None if index == 2 else actual + (2 if index % 2 else -1), 0.3),
            ],
        })
    metrics = {
        "mae": 1.0, "rmse": 1.0, "mse": 1.0, "r2": 0.5, "wape": 1.0,
        "medianAbsoluteError": 1.0, "maximumAbsoluteError": 1.0,
        "clippingCount": 0, "warningCount": 0, "runtimeSeconds": 1.0,
    }
    candidates = [
        {
            "modelId": model_id,
            "candidateClass": "comparison_baseline" if index == 0 else "learned_model",
            "deployabilityClass": "baseline_not_runtime_deployable" if index == 0 else "deployable_learned_model",
            "modelFamily": f"Family{index}", "preprocessingIdentity": str(index + 2) * 64,
            "metrics": copy.deepcopy(metrics),
        }
        for index, model_id in enumerate(IDS)
    ]
    return {
        "rolling": {
            "assessmentId": "11111111-1111-4111-8111-111111111111",
            "datasetId": "2" * 64, "candidateIds": list(IDS), "folds": folds,
            "plannedFoldCount": len(folds), "foldPlanSha256": "3" * 64,
            "target": "target_cases_next_2w", "horizonWeeks": 2,
        },
        "comparison": {"candidates": candidates, "technicalWinnerModelId": IDS[1]},
        "assessmentPath": str((ROOT / "runtime/assessments/11111111-1111-4111-8111-111111111111").resolve()),
        "assessmentCommitSha256": "4" * 64,
        "commit": {"validationRecordSha256": "5" * 64},
    }


def benchmark(source=None, benchmark_id="22222222-2222-4222-8222-222222222222"):
    return build_benchmark(
        benchmark_id=benchmark_id,
        generated_at="2026-01-01T00:00:00Z",
        evidence_scope="synthetic_qualification",
        policy_identity={
            "policyId": "RUNTIME.PORTFOLIO_BENCHMARK.EVIDENCE",
            "policyVersion": "p1-v1", "policySha256": SHA, "policyRawSha256": SHA,
        },
        source=source or source_fixture(), candidate_order=IDS,
        candidate_registry_version="p2-v2", candidate_registry_sha256=SHA,
        assessment_policy_identity={
            "policyId": "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE",
            "policyVersion": "p2-v3", "policySha256": SHA,
        },
        tolerance=1e-9,
    )


class PortfolioBenchmarkEvidenceTests(unittest.TestCase):
    def test_common_cohort_and_candidate_specific_label(self):
        value = benchmark()
        self.assertEqual(value["primaryCohort"]["commonSuccessFoldCount"], 5)
        self.assertNotIn("fold-2", value["primaryCohort"]["orderedCommonFoldIds"])
        negative_binomial = next(
            candidate for candidate in value["candidateSummaries"]
            if candidate["modelId"] == "negative_binomial_regression"
        )
        self.assertEqual((negative_binomial["successfulFolds"], negative_binomial["failedFolds"]), (5, 1))
        self.assertEqual(
            negative_binomial["candidateSpecificCohortLabel"],
            "non_comparable_candidate_specific_cohort",
        )

    def test_metric_formulas_include_bias_and_runtime(self):
        records = [prediction("x", 10, 12, 1), prediction("x", 20, 16, 3)]
        value = metric_summary(records, [10, 20])
        self.assertEqual(value["mae"], 3)
        self.assertAlmostEqual(value["rmse"], math.sqrt(10))
        self.assertEqual(value["wape"], 20)
        self.assertEqual(value["signedMeanError"], -1)
        self.assertEqual(value["medianRuntimeSeconds"], 2)

    def test_fold_wins_baselines_pairwise_and_stability(self):
        value = benchmark()
        self.assertEqual(len(value["pairwiseComparisons"]), 3)
        self.assertEqual(len(value["baselineRelativeSummaries"]), 2)
        self.assertEqual(len(value["foldWinSummaries"]), 3)
        self.assertEqual(len(value["rankingStability"]["firstSecondHalf"]), 2)
        self.assertEqual(len(value["rankingStability"]["contiguousBlocks"]), 3)
        self.assertEqual(len(value["rankingStability"]["perFoldRankDistributions"]), 3)

    def test_correlation_statuses(self):
        self.assertEqual(pearson([1], [1])["status"], "insufficient_samples")
        self.assertEqual(pearson([1, 1], [2, 3])["status"], "constant_series")
        self.assertEqual(pearson([1, float("nan")], [2, 3])["status"], "non_finite_input")
        self.assertEqual(pearson([1, 2, 3], [3, 2, 1])["status"], "computable")

    def test_deterministic_tertiles_and_tie_order(self):
        folds = source_fixture()["rolling"]["folds"][:5]
        folds[0]["actualTarget"] = folds[1]["actualTarget"]
        groups = descriptive_tertiles(folds)
        self.assertEqual([group["foldCount"] for group in groups], [2, 2, 1])
        self.assertEqual(groups[0]["foldIds"], ["fold-1", "fold-2"])
        self.assertTrue(all(group["operationalThreshold"] is False for group in groups))

    def test_synthetic_rationalization_cannot_retire_or_classify_redundancy(self):
        value = benchmark()
        categories = {item["category"] for item in value["rationalization"]["recommendations"]}
        self.assertNotIn("RETIREMENT_CANDIDATE", categories)
        self.assertNotIn("REDUNDANCY_CANDIDATE", categories)
        self.assertEqual(value["rationalization"]["redundancyClassificationStatus"], "not_governed")
        self.assertFalse(value["rationalization"]["automaticRegistryMutationAllowed"])
        self.assertFalse(value["rationalization"]["automaticAssignmentMutationAllowed"])

    def test_duplicate_fold_and_prediction_fail_closed(self):
        source = source_fixture()
        source["rolling"]["folds"].append(copy.deepcopy(source["rolling"]["folds"][0]))
        with self.assertRaisesRegex(PortfolioBenchmarkEvidenceError, "duplicate_fold"):
            benchmark(source)
        source = source_fixture()
        source["rolling"]["folds"][0]["predictions"][1]["modelId"] = IDS[0]
        with self.assertRaisesRegex(PortfolioBenchmarkEvidenceError, "duplicate_candidate_prediction"):
            benchmark(source)

    def test_deterministic_replay_except_identity_fields(self):
        first = benchmark()
        second = benchmark(benchmark_id="33333333-3333-4333-8333-333333333333")
        first.pop("benchmarkId")
        second.pop("benchmarkId")
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )


if __name__ == "__main__":
    unittest.main()
