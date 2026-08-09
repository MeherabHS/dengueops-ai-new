import copy
import json
import shutil
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator, FormatChecker

from tests.test_product_v2_quick_forecast import (
    _create_p2_v2_assignment,
    _setup_quick_run_job,
    build_ready_workspace,
)
from tests.test_runtime_forecast_outcome import build_outcome_job


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_commit import atomic_json, sha256_file
from runtime_forecast_outcome import execute as execute_outcome
from runtime_forecast_outcome_commit import ForecastOutcomeCommitError
from runtime_forecast_outcome_source import ForecastSourceError, verify_forecast_source
from runtime_quick_forecast import execute as execute_quick


def _quick_runtime(base: Path, model_id: str, schema_version: str = "2.1"):
    runtime = _create_p2_v2_assignment(base, ROOT, model_id)
    workspace, dataset_id, validation_sha = build_ready_workspace(runtime)
    job, job_path, staging = _setup_quick_run_job(runtime, workspace.name, dataset_id, validation_sha)
    if schema_version != "2.1":
        job["schemaVersion"] = schema_version
        atomic_json(job_path, job)
    execute_quick(SimpleNamespace(runtime_root=str(runtime), job_record=str(job_path), workspace=str(workspace), staging=str(staging)))
    return runtime, job


def _outcome(runtime: Path, job: dict, observed: int = 123):
    outcome_job, job_path = build_outcome_job(runtime, job, observed=observed, schema_version="2.1")
    result = execute_outcome(SimpleNamespace(runtime_root=str(runtime), job_record=str(job_path), staging=str(runtime / "outcome-staging" / outcome_job["outcomeId"])))
    root = runtime / "forecast-outcomes" / outcome_job["outcomeId"]
    return outcome_job, result, json.loads((root / "artifacts/outcome_evaluation.json").read_text()), json.loads((root / "artifacts/monitoring_summary.json").read_text())


class ProductV2QuickForecastMonitoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temp.name)
        cls.templates = {
            model_id: _quick_runtime(cls.base / "templates" / model_id, model_id)
            for model_id in ("random_forest", "ridge_regression", "poisson_gam")
        }

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def cloned_runtime(self, name: str, model_id: str):
        source, job = self.templates[model_id]
        runtime = self.base / "cases" / name / source.name
        runtime.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, runtime)
        return runtime, copy.deepcopy(job)

    def test_exact_assigned_candidate_interval_monitoring(self):
        for model_id in ("random_forest", "ridge_regression", "poisson_gam"):
            with self.subTest(model_id=model_id):
                runtime, job = self.cloned_runtime(f"monitoring-{model_id}", model_id)
                outcome_job, result, outcome, summary = _outcome(runtime, job)
                self.assertEqual((result["commit"]["schemaVersion"], result["commit"]["policyVersion"]), ("2.1", "p2-v3"))
                self.assertEqual(outcome["sourceFamily"], "quick_forecast_p2")
                self.assertEqual(outcome["sourceEvidence"]["runRecordSha256"], sha256_file(runtime / "runs" / job["runId"] / "metadata/run.json"))
                self.assertEqual(outcome["sourceEvidence"]["assessmentReferenceStatus"], "not_applicable_no_assessment_reference")
                self.assertEqual(outcome["sourceEvidence"]["assignmentProvenance"]["assignmentId"], job["assignmentId"])
                self.assertEqual(summary["evaluatedForecastCount"], 1)
                self.assertEqual(len(summary["performanceAuthorityBreakdowns"]), 1)
                self.assertEqual(len(summary["assignmentProvenanceBreakdowns"]), 1)
                self.assertEqual(outcome["empiricalRangeStatus"], "available")
                self.assertEqual(summary["empiricalRangeEvaluatedCount"], 1)
                self.assertIsNotNone(outcome["lowerRaw"])
                self.assertIsNotNone(outcome["upperRaw"])
                self.assertIsNotNone(outcome["intervalWidth"])

    def test_publisher_generated_assignment_2_0_schemas_and_hashes(self):
        runtime, job = self.cloned_runtime("assignment-schema", "ridge_regression")
        assignment = runtime / "model-assignments" / job["assignmentId"]
        record_path = assignment / "artifacts/assignment_record.json";commit_path = assignment / "metadata/commit.json"
        record = json.loads(record_path.read_text());commit = json.loads(commit_path.read_text())
        for value, name in ((record, "runtime_model_assignment.schema.json"), (commit, "runtime_model_assignment_commit.schema.json")):
            schema = json.loads((ROOT / "config" / name).read_text())
            self.assertFalse(list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value)))
            extra = {**value, "unexpected": True}
            self.assertTrue(list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(extra)))
        self.assertEqual(sha256_file(record_path), commit["assignmentRecordSha256"])
        self.assertEqual(sha256_file(commit_path), job["assignmentCommitSha256"])
        missing = dict(commit);missing.pop("assignmentRecordSha256")
        schema = json.loads((ROOT / "config/runtime_model_assignment_commit.schema.json").read_text())
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(missing)))
        for value, name in ((record, "runtime_model_assignment.schema.json"), (commit, "runtime_model_assignment_commit.schema.json")):
            validator = Draft202012Validator(json.loads((ROOT / "config" / name).read_text()))
            wrong_version = {**value, "schemaVersion": "2.1"}
            self.assertTrue(list(validator.iter_errors(wrong_version)))

    def test_mixed_assignment_contract_versions_fail_source_verification(self):
        runtime, job = self.cloned_runtime("assignment-mixed", "ridge_regression")
        run = runtime / "runs" / job["runId"]
        assignment_commit = runtime / "model-assignments" / job["assignmentId"] / "metadata/commit.json"
        value = json.loads(assignment_commit.read_text());value["schemaVersion"] = "1.0";atomic_json(assignment_commit, value)
        with self.assertRaises(ForecastSourceError):
            verify_forecast_source(runtime, job["runId"], sha256_file(run / "metadata/commit.json"), {"quick_forecast_p2"})

    def test_quick_2_0_is_readable_but_monitoring_ineligible(self):
        runtime, job = _quick_runtime(self.base / "quick-20", "ridge_regression", "2.0")
        run = runtime / "runs" / job["runId"]
        self.assertEqual(json.loads((run / "artifacts/forecast_output.json").read_text())["schemaVersion"], "2.0")
        with self.assertRaises(ForecastSourceError) as caught:
            verify_forecast_source(runtime, job["runId"], sha256_file(run / "metadata/commit.json"), {"quick_forecast_p2"})
        self.assertEqual(caught.exception.code, "forecast_not_eligible")
        outcome_job, path = build_outcome_job(runtime, job, schema_version="2.1")
        with self.assertRaises(ForecastOutcomeCommitError):
            execute_outcome(SimpleNamespace(runtime_root=str(runtime), job_record=str(path), staging=str(runtime / "outcome-staging" / outcome_job["outcomeId"])))
        self.assertFalse((runtime / "forecast-outcomes" / outcome_job["outcomeId"]).exists())
        self.assertFalse((runtime / "deployments/dhaka_south/monitoring/latest.json").exists())

    def test_assignment_and_authority_tampering_fails_closed(self):
        runtime, job = self.cloned_runtime("tamper-base", "ridge_regression")
        run = runtime / "runs" / job["runId"];original_commit = (run / "metadata/commit.json").read_bytes()
        commit_sha = sha256_file(run / "metadata/commit.json")
        assignment = runtime / "model-assignments" / job["assignmentId"]
        record_path = assignment / "artifacts/assignment_record.json";record_bytes = record_path.read_bytes()
        record = json.loads(record_bytes);record["modelFamily"] = "RandomForestRegressor";atomic_json(record_path, record)
        with self.assertRaises(ForecastSourceError):
            verify_forecast_source(runtime, job["runId"], commit_sha, {"quick_forecast_p2"})
        record_path.write_bytes(record_bytes)
        assignment_commit = assignment / "metadata/commit.json";assignment_commit_bytes = assignment_commit.read_bytes()
        value = json.loads(assignment_commit_bytes);value["assignmentRecordSha256"] = "0" * 64;atomic_json(assignment_commit, value)
        with self.assertRaises(ForecastSourceError):
            verify_forecast_source(runtime, job["runId"], commit_sha, {"quick_forecast_p2"})
        assignment_commit.write_bytes(assignment_commit_bytes)
        assignment_commit.write_bytes(assignment_commit_bytes + b"\n")
        with self.assertRaises(ForecastSourceError):
            verify_forecast_source(runtime, job["runId"], commit_sha, {"quick_forecast_p2"})
        assignment_commit.write_bytes(assignment_commit_bytes)
        for field, replacement in (
            ("assignmentId", "00000000-0000-4000-8000-000000000000"),
            ("deploymentId", "other_deployment"),
            ("assignmentAction", "retain"),
            ("modelId", "random_forest"),
            ("modelFamily", "RandomForestRegressor"),
            ("parameterSha256", "0" * 64),
            ("preprocessingIdentity", "0" * 64),
            ("candidateRegistrySha256", "0" * 64),
            ("featureOrderSha256", "0" * 64),
        ):
            with self.subTest(field=field):
                changed = json.loads(record_bytes);changed[field] = replacement;atomic_json(record_path, changed)
                with self.assertRaises(ForecastSourceError):
                    verify_forecast_source(runtime, job["runId"], commit_sha, {"quick_forecast_p2"})
                record_path.write_bytes(record_bytes)
        self.assertEqual((run / "metadata/commit.json").read_bytes(), original_commit)

    def test_artifact_tampering_does_not_publish_outcome_or_latest(self):
        source_runtime, source_job = self.cloned_runtime("artifact-source", "ridge_regression")
        for artifact in ("forecast_output.json", "model_card.json", "forecast_calibration.json", "forecast_uncertainty.json"):
            with self.subTest(artifact=artifact):
                runtime = self.base / f"artifact-{artifact}" / source_runtime.name
                runtime.parent.mkdir(parents=True)
                shutil.copytree(source_runtime, runtime)
                job = copy.deepcopy(source_job)
                path = runtime / "runs" / job["runId"] / "artifacts" / artifact
                path.write_bytes(path.read_bytes() + b"\n")
                outcome_job, job_path = build_outcome_job(runtime, job, schema_version="2.1")
                with self.assertRaises(ForecastOutcomeCommitError):
                    execute_outcome(SimpleNamespace(runtime_root=str(runtime), job_record=str(job_path), staging=str(runtime / "outcome-staging" / outcome_job["outcomeId"])))
                self.assertFalse((runtime / "forecast-outcomes" / outcome_job["outcomeId"]).exists())
                self.assertFalse((runtime / "deployments/dhaka_south/monitoring/latest.json").exists())

    def test_later_assignment_does_not_change_historical_attribution(self):
        runtime, job = self.cloned_runtime("historical-authority", "ridge_regression")
        original = verify_forecast_source(runtime, job["runId"], sha256_file(runtime / "runs" / job["runId"] / "metadata/commit.json"), {"quick_forecast_p2"})
        pointer = runtime / "deployments/dhaka_south/model-assignment/latest.json"
        changed = json.loads(pointer.read_text());changed["assignmentId"] = "00000000-0000-4000-8000-000000000000";atomic_json(pointer, changed)
        after = verify_forecast_source(runtime, job["runId"], sha256_file(runtime / "runs" / job["runId"] / "metadata/commit.json"), {"quick_forecast_p2"})
        self.assertEqual(after["assignment"], original["assignment"])
        _, _, outcome, _ = _outcome(runtime, job)
        self.assertEqual(outcome["sourceEvidence"]["assignmentProvenance"]["assignmentId"], job["assignmentId"])


if __name__ == "__main__":
    unittest.main()
