import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_forecast_outcome import execute as execute_outcome
from runtime_model_degradation_evidence import (
    build_model_degradation_evidence,
    execute as execute_degradation,
)
from runtime_model_degradation_policy import load_and_validate_model_degradation_policy
from runtime_model_degradation_source import verify_model_degradation_source
from runtime_worker import run_once
from tests.test_runtime_forecast_outcome import build_outcome_job
from tests.test_runtime_job_runner import build_pending_governed_quick_job
from tests.test_runtime_model_degradation_evidence import degradation_job


class ProductV2ModelDegradationTests(unittest.TestCase):
    def test_quick_p2_ridge_is_point_only_descriptive_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _, forecast_job = build_pending_governed_quick_job(Path(directory), "2.1")
            self.assertTrue(run_once(runtime, "b8-quick-p2"))
            outcome_job, outcome_path = build_outcome_job(
                runtime,
                forecast_job,
                record_id="b8-ridge-point-only",
                schema_version="2.1",
            )
            execute_outcome(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(outcome_path),
                    staging=str(runtime / "outcome-staging" / outcome_job["outcomeId"]),
                )
            )
            job, job_path = degradation_job(runtime)
            result = execute_degradation(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(job_path),
                    staging=str(runtime / "degradation-staging" / job["evidenceId"]),
                )
            )
            evidence_root = runtime / "degradation-evidence" / job["evidenceId"]
            evidence = json.loads(
                (evidence_root / "artifacts/degradation_evidence.json").read_text()
            )
            commit = json.loads((evidence_root / "metadata/commit.json").read_text())
            cohort = evidence["cohorts"][0]
            population = cohort["actualPopulation"]

            self.assertEqual(cohort["identity"]["sourceFamily"], "quick_forecast_p2")
            self.assertEqual(cohort["identity"]["modelId"], "ridge_regression")
            self.assertEqual(cohort["identity"]["forecastPresentationMode"], "point_only")
            self.assertEqual(cohort["identity"]["calibrationStatus"], "unavailable")
            self.assertEqual(population["rangeEligibleCount"], 0)
            self.assertEqual(population["empiricalRangeEvaluatedCount"], 0)
            self.assertIsNone(population["empiricalCoverage"])
            self.assertIn("range_metric_unavailable", cohort["warnings"])
            self.assertEqual(evidence["evidenceStatus"], "evidence_only")
            self.assertEqual(evidence["degradationThresholdStatus"], "not_governed")
            self.assertFalse(evidence["materialWorseningClassificationAllowed"])
            self.assertFalse(evidence["lifecycleRecommendationAllowed"])
            self.assertFalse(evidence["lifecycleActionProduced"])
            self.assertFalse(commit["lifecycleActionProduced"])
            self.assertEqual(
                set(commit["artifactHashes"]),
                {
                    "degradation_evidence.json",
                    "degradation_summary.json",
                    "monitoring_latest_snapshot.json",
                },
            )
            self.assertEqual(result["pointer"]["policyVersion"], "p2-v2")
            self.assertTrue(
                (runtime / "deployments/dhaka_south/degradation/latest_p2-v2.json").is_file()
            )
            self.assertFalse(
                (runtime / "deployments/dhaka_south/degradation/latest.json").exists()
            )

            source = verify_model_degradation_source(
                runtime,
                job["expectedMonitoringLatestSha256"],
                job["expectedMonitoringSummarySha256"],
                job["expectedIncludedOutcomeSetSha256"],
                "p2-v2",
            )
            second = copy.deepcopy(source["outcomes"][0])
            second["outcomeId"] = "00000000-0000-4000-8000-000000000002"
            second["outcomeCommitSha256"] = "2" * 64
            second["outcomeEvidenceSha256"] = "3" * 64
            second["forecastTargetPeriod"] = "2025-W02"
            second["sourceEvidence"]["assignmentProvenance"]["assignmentId"] = "00000000-0000-4000-8000-000000000003"
            second["sourceEvidence"]["assignmentProvenance"]["assignmentCommitSha256"] = "4" * 64
            synthetic_source = {**source, "outcomes": [source["outcomes"][0], second]}
            policy, policy_sha = load_and_validate_model_degradation_policy()
            merged, _ = build_model_degradation_evidence(
                job,
                policy,
                policy_sha,
                synthetic_source,
                evidence["generatedAt"],
            )
            self.assertEqual(len(merged["cohorts"]), 1)
            self.assertEqual(len(merged["cohorts"][0]["assignmentProvenance"]), 2)

    def test_representative_additional_governed_model_remains_descriptive(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _, forecast_job = build_pending_governed_quick_job(
                Path(directory),
                "2.1",
                model_id="gradient_boosting",
            )
            self.assertTrue(run_once(runtime, "b8-additional-model"))
            outcome_job, outcome_path = build_outcome_job(
                runtime,
                forecast_job,
                record_id="b8-gradient-boosting",
                schema_version="2.1",
            )
            execute_outcome(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(outcome_path),
                    staging=str(runtime / "outcome-staging" / outcome_job["outcomeId"]),
                )
            )
            job, job_path = degradation_job(runtime)
            execute_degradation(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(job_path),
                    staging=str(runtime / "degradation-staging" / job["evidenceId"]),
                )
            )
            evidence = json.loads(
                (
                    runtime
                    / "degradation-evidence"
                    / job["evidenceId"]
                    / "artifacts/degradation_evidence.json"
                ).read_text()
            )
            cohort = evidence["cohorts"][0]
            self.assertEqual(cohort["identity"]["modelId"], "gradient_boosting")
            self.assertEqual(cohort["identity"]["sourceFamily"], "quick_forecast_p2")
            self.assertEqual(evidence["evidenceStatus"], "evidence_only")
            self.assertEqual(evidence["materialWorseningStatus"], "not_governed")

    def test_quick_p2_random_forest_has_descriptive_empirical_range_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _, forecast_job = build_pending_governed_quick_job(
                Path(directory),
                "2.1",
                model_id="random_forest",
            )
            self.assertTrue(run_once(runtime, "b8-rf-interval"))
            outcome_job, outcome_path = build_outcome_job(
                runtime,
                forecast_job,
                record_id="b8-rf-interval",
                schema_version="2.1",
            )
            execute_outcome(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(outcome_path),
                    staging=str(runtime / "outcome-staging" / outcome_job["outcomeId"]),
                )
            )
            job, job_path = degradation_job(runtime)
            execute_degradation(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(job_path),
                    staging=str(runtime / "degradation-staging" / job["evidenceId"]),
                )
            )
            evidence = json.loads(
                (
                    runtime
                    / "degradation-evidence"
                    / job["evidenceId"]
                    / "artifacts/degradation_evidence.json"
                ).read_text()
            )
            cohort = evidence["cohorts"][0]
            population = cohort["actualPopulation"]
            self.assertEqual(cohort["identity"]["modelId"], "random_forest")
            self.assertEqual(cohort["identity"]["forecastPresentationMode"], "point_and_interval")
            self.assertEqual(cohort["identity"]["calibrationStatus"], "governed_available")
            self.assertEqual(population["empiricalRangeEvaluatedCount"], 1)
            self.assertEqual(
                population["empiricalRangeCoveredCount"]
                + population["lowerMissCount"]
                + population["upperMissCount"],
                1,
            )
            self.assertIsNotNone(population["empiricalCoverage"])
            self.assertEqual(evidence["evidenceStatus"], "evidence_only")
            self.assertEqual(evidence["materialWorseningStatus"], "not_governed")


if __name__ == "__main__":
    unittest.main()
