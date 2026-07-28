import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_commit import sha256_file
from runtime_forecast_outcome import execute as execute_outcome
from runtime_model_degradation_evidence import execute as execute_degradation
from runtime_quick_forecast import execute as execute_quick
from tests.test_product_v2_quick_forecast import (
    _create_p2_v2_assignment,
    _setup_quick_run_job,
    build_ready_workspace,
)
from tests.test_runtime_forecast_outcome import build_outcome_job
from tests.test_runtime_model_degradation_evidence import degradation_job


class PoissonGamGovernedWorkflowTests(unittest.TestCase):
    def test_assigned_gam_is_point_only_through_quick_monitoring_and_degradation(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(
                _create_p2_v2_assignment(
                    Path(directory), ROOT, model_id="poisson_gam"
                )
            )

            approved_pointer = json.loads(
                (runtime / "deployments/dhaka_south/latest.json").read_text()
            )
            approved_run = runtime / "runs" / approved_pointer["runId"]
            approved_uncertainty = json.loads(
                (
                    approved_run / "artifacts/forecast_uncertainty.json"
                ).read_text()
            )
            self.assertEqual(
                (
                    approved_uncertainty["forecastPresentationMode"],
                    approved_uncertainty["calibrationStatus"],
                    approved_uncertainty["uncertaintyReasonCode"],
                ),
                (
                    "point_only",
                    "unavailable",
                    "model_calibration_unavailable",
                ),
            )

            workspace, dataset_id, validation_sha = build_ready_workspace(runtime)
            quick_job, job_path, staging = _setup_quick_run_job(
                runtime, workspace.name, dataset_id, validation_sha
            )
            result = execute_quick(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(job_path),
                    workspace=str(workspace),
                    staging=str(staging),
                )
            )
            self.assertTrue(result["committed"])
            quick_run = runtime / "runs" / quick_job["runId"]
            forecast = json.loads(
                (quick_run / "artifacts/forecast_output.json").read_text()
            )
            calibration = json.loads(
                (quick_run / "artifacts/forecast_calibration.json").read_text()
            )
            self.assertEqual(forecast["activeModelId"], "poisson_gam")
            self.assertEqual(forecast["forecastPresentationMode"], "point_only")
            self.assertEqual(forecast["calibrationStatus"], "unavailable")
            self.assertEqual(calibration["calibrationStatus"], "unavailable")
            self.assertEqual(calibration["residualCount"], 0)
            self.assertEqual(calibration["folds"], [])

            outcome_job, outcome_path = build_outcome_job(
                runtime,
                quick_job,
                record_id="poisson-gam-governed-workflow",
                schema_version="2.1",
            )
            execute_outcome(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(outcome_path),
                    staging=str(
                        runtime
                        / "outcome-staging"
                        / outcome_job["outcomeId"]
                    ),
                )
            )
            outcome_root = runtime / "forecast-outcomes" / outcome_job["outcomeId"]
            outcome = json.loads(
                (
                    outcome_root / "artifacts/outcome_evaluation.json"
                ).read_text()
            )
            self.assertEqual(outcome["modelId"], "poisson_gam")
            self.assertEqual(
                outcome["empiricalRangeStatus"],
                "not_evaluable_model_calibration_unavailable",
            )
            self.assertIsNone(outcome["lowerRaw"])
            self.assertIsNone(outcome["upperRaw"])

            evidence_job, evidence_path = degradation_job(runtime)
            degradation = execute_degradation(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(evidence_path),
                    staging=str(
                        runtime
                        / "degradation-staging"
                        / evidence_job["evidenceId"]
                    ),
                )
            )
            evidence_root = (
                runtime / "degradation-evidence" / evidence_job["evidenceId"]
            )
            evidence = json.loads(
                (
                    evidence_root / "artifacts/degradation_evidence.json"
                ).read_text()
            )
            cohort = evidence["cohorts"][0]
            self.assertEqual(cohort["identity"]["modelId"], "poisson_gam")
            self.assertEqual(cohort["identity"]["calibrationStatus"], "unavailable")
            self.assertIsNone(
                cohort["actualPopulation"]["empiricalCoverage"]
            )
            self.assertEqual(degradation["pointer"]["policyVersion"], "p2-v3")
            self.assertEqual(
                degradation["pointer"]["commitSha256"],
                sha256_file(evidence_root / "metadata/commit.json"),
            )


if __name__ == "__main__":
    unittest.main()
