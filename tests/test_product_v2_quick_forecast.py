"""Comprehensive tests for B5 Product-v2 Quick Forecast."""

import hashlib
import json
import shutil
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_commit import RuntimeCommitError, atomic_json, commit_runtime_run, sha256_file
from model_factory import load_and_validate_candidate_registry
from runtime_quick_forecast import execute
from runtime_policy import load_and_validate_quick_forecast_policy
from runtime_validate import validate
from runtime_active_model import resolve_active_model_p2_v2, ActiveModelError
from analytics.runtime_model_lifecycle_commit import commit_lifecycle_action


def build_ready_workspace(base: Path) -> tuple[Path, str, str]:
    workspace_id = str(uuid.uuid4())
    workspace = base / "workspaces" / workspace_id
    for relative in ("metadata", "inputs/original", "inputs/canonical", "logs"):
        (workspace / relative).mkdir(parents=True, exist_ok=True)
    dengue = workspace / "inputs/original/dengue.csv"
    climate = workspace / "inputs/original/climate.csv"
    shutil.copy2(ROOT / "data/dengue_cases.csv", dengue)
    shutil.copy2(ROOT / "data/climate_data.csv", climate)
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = validate(SimpleNamespace(
        workspace_root=str(workspace), workspace_id=workspace_id, created_at=created,
        dengue_input=str(dengue), climate_input=str(climate),
        canonical_dengue_output=str(workspace / "inputs/canonical/dengue_cases.csv"),
        canonical_climate_output=str(workspace / "inputs/canonical/climate_data.csv"),
        validation_output=str(workspace / "metadata/validation.json"),
        deployment_id="dhaka_south", workflow_mode="quick_forecast",
    ))
    metadata = {
        "schemaVersion": "1.0", "workspaceId": workspace_id, "correlationId": str(uuid.uuid4()),
        "deploymentId": "dhaka_south", "workflowMode": "quick_forecast", "status": "ready",
        "createdAt": created, "updatedAt": created, "originalFiles": {}, "datasetId": result["datasetId"]
    }
    atomic_json(workspace / "metadata/workspace.json", metadata)
    val_sha = hashlib.sha256((workspace / "metadata/validation.json").read_bytes()).hexdigest()
    return workspace, result["datasetId"], val_sha


def _setup_quick_run_job(runtime_root: Path, workspace_id: str, dataset_id: str, val_sha: str) -> tuple[dict, Path, Path]:
    job_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    job = {
        "schemaVersion": "1.0",
        "jobKind": "quick_forecast",
        "jobId": job_id,
        "runId": run_id,
        "workspaceId": workspace_id,
        "datasetId": dataset_id,
        "deploymentId": "dhaka_south",
        "workflowMode": "quick_forecast",
        "validationRecordSha256": val_sha,
        "status": "running",
        "progress": "starting",
        "createdAt": now,
        "updatedAt": now
    }

    job_file = runtime_root / "jobs/running" / f"{job_id}.json"
    job_file.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(job_file, job)

    workspace_dir = runtime_root / "workspaces" / workspace_id
    staging_dir = runtime_root / "staging" / run_id
    staging_dir.mkdir(parents=True, exist_ok=True)

    return job, job_file, staging_dir


def _create_p2_v2_assignment(runtime_root: Path, repository_root: Path, model_id: str = "ridge_regression") -> str:
    from tests.lifecycle_fixtures import build_one_run_chain_p2_v2
    chain = build_one_run_chain_p2_v2(runtime_root / "fixture_base", repository_root, model_id=model_id)
    dest_runtime = (runtime_root / f"runtime_{model_id}_{uuid.uuid4().hex[:8]}").resolve()
    shutil.copytree(chain["runtime"], dest_runtime)

    commit_res = commit_lifecycle_action(
        runtime_root=dest_runtime,
        one_run_forecast_run_id=chain["runId"],
        reason=f"Governed B5 test assignment for {model_id}",
        operator_identifier="b5-test-operator",
        acknowledgement=True,
        repository_root=repository_root
    )
    assert commit_res["success"] is True, f"Failed to commit assignment for {model_id}: {commit_res}"
    return dest_runtime


class ProductV2QuickForecastTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = ROOT / "tmp" / f"quick_p2_test_{uuid.uuid4().hex[:8]}"
        self.test_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_quick_forecast_p2_succeeds_for_all_eight_learned_candidates(self):
        learned_candidates = [
            "random_forest",
            "ridge_regression",
            "poisson_regression",
            "gradient_boosting",
            "elastic_net",
            "negative_binomial_regression",
            "extra_trees",
            "hist_gradient_boosting"
        ]
        registry, registry_sha = load_and_validate_candidate_registry()
        registry_by_id = {candidate["model_id"]: candidate for candidate in registry["candidates"]}

        for model_id in learned_candidates:
            with self.subTest(model_id=model_id):
                runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id=model_id)
                workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)

                job, job_file, staging_dir = _setup_quick_run_job(
                    runtime_root, workspace_dir.name, dataset_id, val_sha
                )

                args = SimpleNamespace(
                    runtime_root=str(runtime_root),
                    job_record=str(job_file),
                    workspace=str(workspace_dir),
                    staging=str(staging_dir)
                )

                result = execute(args)
                self.assertTrue(result["committed"])
                self.assertEqual(result["runId"], job["runId"])

                committed_run = runtime_root / "runs" / job["runId"]
                forecast_output = json.loads((committed_run / "artifacts/forecast_output.json").read_text(encoding="utf-8"))
                model_card = json.loads((committed_run / "artifacts/model_card.json").read_text(encoding="utf-8"))
                uncertainty = json.loads((committed_run / "artifacts/forecast_uncertainty.json").read_text(encoding="utf-8"))
                calibration = json.loads((committed_run / "artifacts/forecast_calibration.json").read_text(encoding="utf-8"))
                run_record = json.loads((committed_run / "metadata/run.json").read_text(encoding="utf-8"))
                candidate = registry_by_id[model_id]

                self.assertEqual(forecast_output["activeModelId"], model_id)
                self.assertEqual(forecast_output["sourceFamily"], "quick_forecast_p2")
                self.assertEqual(forecast_output["policy"]["version"], "p2-v1")
                self.assertEqual(forecast_output["policy"]["id"], "RUNTIME.QUICK_FORECAST.COMPATIBILITY")
                self.assertEqual(forecast_output["policy"]["sha256"], "4a6f166d037ab4c69df980549626d993db473bcec325fa2a68dbe5f8485a757e")
                self.assertEqual(model_card["model"]["id"], model_id)
                self.assertEqual(model_card["sourceFamily"], "quick_forecast_p2")
                self.assertEqual(uncertainty["activeModelId"], model_id)
                self.assertEqual(uncertainty["sourceFamily"], "quick_forecast_p2")
                for artifact in (forecast_output, uncertainty, calibration, model_card, run_record):
                    self.assertEqual(artifact["schemaVersion"], "2.0")
                self.assertEqual(run_record["modelFamily"], candidate["model_family"])
                self.assertEqual(run_record["parameterSha256"], candidate["parameters_sha256"])
                self.assertEqual(run_record["preprocessingIdentity"], candidate["preprocessing_identity"])
                self.assertEqual(run_record["candidateRegistrySha256"], registry_sha)
                self.assertEqual(run_record["featureOrderSha256"], candidate["feature_order_sha256"])
                if model_id == "random_forest":
                    self.assertEqual(calibration["calibrationStatus"], "governed_available")
                    self.assertEqual(calibration["residualCount"], 68)
                    self.assertEqual(len(calibration["folds"]), 68)
                else:
                    self.assertEqual(calibration["calibrationStatus"], "unavailable")
                    self.assertEqual(calibration["residualCount"], 0)
                    self.assertEqual(calibration["folds"], [])


    def test_quick_forecast_p2_fails_when_active_model_not_assigned(self):
        runtime_root = self.test_dir / "unassigned_runtime"
        runtime_root.mkdir(parents=True, exist_ok=True)
        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)

        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_fails_when_only_p1_v1_historical_assignment_exists(self):
        runtime_root = self.test_dir / "historical_p1_runtime"
        assignment_root = runtime_root / "deployments/dhaka_south/model-assignment"
        assignment_root.mkdir(parents=True, exist_ok=True)
        atomic_json(assignment_root / "latest.json", {
            "schemaVersion": "1.0",
            "assignmentId": str(uuid.uuid4()),
            "assignedModelId": "random_forest",
            "policyVersion": "p2-v1"
        })

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_fails_when_profile_json_exists_without_p2_assignment(self):
        runtime_root = self.test_dir / "profile_only_runtime"
        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)

        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_rejects_client_supplied_model_id(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)

        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        job["modelId"] = "random_forest"
        job["resolvedModelId"] = "random_forest"
        atomic_json(job_file, job)

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        result = execute(args)
        committed_run = runtime_root / "runs" / job["runId"]
        forecast_output = json.loads((committed_run / "artifacts/forecast_output.json").read_text(encoding="utf-8"))
        self.assertEqual(forecast_output["activeModelId"], "ridge_regression")

    def test_quick_forecast_p2_fails_closed_for_baseline_or_diagnostic_active_model(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")

        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["assignedModelId"] = "moving_average_4w"
        pointer["modelFamily"] = "MovingAverage4W"
        pointer["parameterSha256"] = "c1eff3c6bc5cf02b7176abcbf33348f0d3962791d002686d53e6654cae04a18c"
        atomic_json(pointer_path, pointer)

        record_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "artifacts/assignment_record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["modelId"] = "moving_average_4w"
        record["modelFamily"] = "MovingAverage4W"
        record["parameterSha256"] = "c1eff3c6bc5cf02b7176abcbf33348f0d3962791d002686d53e6654cae04a18c"
        atomic_json(record_path, record)

        commit_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "metadata/commit.json"
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        commit["assignmentRecordSha256"] = sha256_file(record_path)
        atomic_json(commit_path, commit)

        pointer["assignmentCommitSha256"] = sha256_file(commit_path)
        atomic_json(pointer_path, pointer)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("selectable learned candidate", str(cm.exception))

    def test_quick_forecast_p2_fails_closed_when_pointer_tampered(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["assignmentCommitSha256"] = "0" * 64
        atomic_json(pointer_path, pointer)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_fails_closed_when_assignment_record_tampered(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        record_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "artifacts/assignment_record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["reason"] = "Tampered assignment record content"
        atomic_json(record_path, record)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_fails_closed_when_assignment_commit_tampered(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        commit_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "metadata/commit.json"
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        commit["assignmentRecordSha256"] = "0" * 64
        atomic_json(commit_path, commit)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_fails_closed_on_candidate_registry_mismatch(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["candidateRegistrySha256"] = "0" * 64
        atomic_json(pointer_path, pointer)

        record_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "artifacts/assignment_record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["candidateRegistrySha256"] = "0" * 64
        atomic_json(record_path, record)

        commit_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "metadata/commit.json"
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        commit["assignmentRecordSha256"] = sha256_file(record_path)
        atomic_json(commit_path, commit)
        pointer["assignmentCommitSha256"] = sha256_file(commit_path)
        atomic_json(pointer_path, pointer)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_fails_closed_on_feature_order_mismatch(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["featureOrderSha256"] = "0" * 64
        atomic_json(pointer_path, pointer)

        record_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "artifacts/assignment_record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["featureOrderSha256"] = "0" * 64
        atomic_json(record_path, record)

        commit_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "metadata/commit.json"
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        commit["assignmentRecordSha256"] = sha256_file(record_path)
        atomic_json(commit_path, commit)
        pointer["assignmentCommitSha256"] = sha256_file(commit_path)
        atomic_json(pointer_path, pointer)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("active_model_not_assigned", str(cm.exception))

    def test_quick_forecast_p2_fails_closed_on_model_family_mismatch(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["modelFamily"] = "InvalidFamilyName"
        atomic_json(pointer_path, pointer)

        record_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "artifacts/assignment_record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["modelFamily"] = "InvalidFamilyName"
        atomic_json(record_path, record)

        commit_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "metadata/commit.json"
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        commit["assignmentRecordSha256"] = sha256_file(record_path)
        atomic_json(commit_path, commit)
        pointer["assignmentCommitSha256"] = sha256_file(commit_path)
        atomic_json(pointer_path, pointer)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("Model family mismatch", str(cm.exception))

    def test_quick_forecast_p2_fails_closed_on_parameter_sha_mismatch(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        pointer["parameterSha256"] = "0" * 64
        atomic_json(pointer_path, pointer)

        record_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "artifacts/assignment_record.json"
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["parameterSha256"] = "0" * 64
        atomic_json(record_path, record)

        commit_path = runtime_root / "model-assignments" / pointer["assignmentId"] / "metadata/commit.json"
        commit = json.loads(commit_path.read_text(encoding="utf-8"))
        commit["assignmentRecordSha256"] = sha256_file(record_path)
        atomic_json(commit_path, commit)
        pointer["assignmentCommitSha256"] = sha256_file(commit_path)
        atomic_json(pointer_path, pointer)

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        with self.assertRaises(ValueError) as cm:
            execute(args)
        self.assertIn("Parameter SHA mismatch", str(cm.exception))

    def test_quick_forecast_p2_point_only_uncertainty_succeeds_when_exact_calibration_unavailable(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="ridge_regression")
        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)

        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        result = execute(args)
        self.assertTrue(result["committed"])

        committed_run = runtime_root / "runs" / job["runId"]
        uncertainty = json.loads((committed_run / "artifacts/forecast_uncertainty.json").read_text(encoding="utf-8"))
        calibration_path = committed_run / "artifacts/forecast_calibration.json"
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))

        self.assertEqual(uncertainty["forecastPresentationMode"], "point_only")
        self.assertEqual(uncertainty["calibrationStatus"], "unavailable")
        self.assertEqual(uncertainty["uncertaintyReasonCode"], "model_calibration_unavailable")
        self.assertIsNone(uncertainty["lowerRaw"])
        self.assertIsNone(uncertainty["upperRaw"])
        self.assertIsNone(uncertainty["lowerReported"])
        self.assertIsNone(uncertainty["upperReported"])
        self.assertEqual(calibration["calibrationStatus"], "unavailable")
        self.assertEqual(calibration["residualCount"], 0)
        self.assertEqual(calibration["folds"], [])

    def test_quick_forecast_p2_point_and_interval_requires_exact_calibration_provenance(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="random_forest")
        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)

        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        result = execute(args)
        self.assertTrue(result["committed"])

        committed_run = runtime_root / "runs" / job["runId"]
        uncertainty = json.loads((committed_run / "artifacts/forecast_uncertainty.json").read_text(encoding="utf-8"))
        calibration_path = committed_run / "artifacts/forecast_calibration.json"
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))

        self.assertEqual(uncertainty["forecastPresentationMode"], "point_and_interval")
        self.assertEqual(uncertainty["calibrationStatus"], "governed_available")
        self.assertIsNotNone(uncertainty["lowerReported"])
        self.assertIsNotNone(uncertainty["upperReported"])
        self.assertLessEqual(uncertainty["lowerReported"], uncertainty["upperReported"])
        self.assertEqual(uncertainty["residualSourceArtifactSha256"], sha256_file(calibration_path))
        self.assertEqual(calibration["calibrationStatus"], "governed_available")
        self.assertEqual(len(calibration["folds"]), 68)

    def test_p2_commit_rejects_mixed_contracts_artifact_tampering_fold_tampering_and_authority_change(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="random_forest")
        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(runtime_root, workspace_dir.name, dataset_id, val_sha)
        args = SimpleNamespace(runtime_root=str(runtime_root), job_record=str(job_file), workspace=str(workspace_dir), staging=str(staging_dir))
        with patch("runtime_quick_forecast.commit_runtime_run", return_value={"pointer": {}}):
            execute(args)
        claimed_job = json.loads(job_file.read_text(encoding="utf-8"))
        quick_pointer = runtime_root / "deployments/dhaka_south/latest.json"
        original_quick_pointer = quick_pointer.read_bytes() if quick_pointer.exists() else None

        calibration_path = staging_dir / "artifacts/forecast_calibration.json"
        original_calibration = calibration_path.read_bytes()
        calibration = json.loads(original_calibration)
        calibration["folds"][0]["absoluteResidual"] += 1
        atomic_json(calibration_path, calibration)
        tampered_calibration_sha = sha256_file(calibration_path)
        card_path = staging_dir / "artifacts/model_card.json"
        original_card = card_path.read_bytes()
        card = json.loads(original_card)
        card["calibration"]["artifactSha256"] = tampered_calibration_sha
        card["artifactHashes"]["forecast_calibration.json"] = tampered_calibration_sha
        atomic_json(card_path, card)
        dashboard_path = staging_dir / "artifacts/dashboard_summary.json"
        original_dashboard = dashboard_path.read_bytes()
        dashboard = json.loads(original_dashboard)
        dashboard["evidence"]["calibration"]["sha256"] = tampered_calibration_sha
        atomic_json(dashboard_path, dashboard)
        with self.assertRaisesRegex(RuntimeCommitError, "residual does not recompute"):
            commit_runtime_run(runtime_root, staging_dir, claimed_job)
        calibration_path.write_bytes(original_calibration)
        card_path.write_bytes(original_card)
        dashboard_path.write_bytes(original_dashboard)

        uncertainty_path = staging_dir / "artifacts/forecast_uncertainty.json"
        original_uncertainty = uncertainty_path.read_bytes()
        uncertainty = json.loads(original_uncertainty)
        uncertainty["schemaVersion"] = "1.0"
        atomic_json(uncertainty_path, uncertainty)
        with self.assertRaisesRegex(RuntimeCommitError, "failed its runtime schema|Mixed p1/p2"):
            commit_runtime_run(runtime_root, staging_dir, claimed_job)
        uncertainty_path.write_bytes(original_uncertainty)

        forecast_path = staging_dir / "artifacts/forecast_output.json"
        original_forecast = forecast_path.read_bytes()
        forecast = json.loads(original_forecast)
        forecast["modelFamily"] = "TamperedModelFamily"
        atomic_json(forecast_path, forecast)
        with self.assertRaisesRegex(RuntimeCommitError, "artifact authority identity mismatch"):
            commit_runtime_run(runtime_root, staging_dir, claimed_job)
        forecast_path.write_bytes(original_forecast)

        assignment_pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
        assignment_pointer = json.loads(assignment_pointer_path.read_text(encoding="utf-8"))
        assignment_pointer["assignmentCommitSha256"] = "0" * 64
        atomic_json(assignment_pointer_path, assignment_pointer)
        with self.assertRaises(ValueError):
            commit_runtime_run(runtime_root, staging_dir, claimed_job)
        self.assertEqual(quick_pointer.read_bytes() if quick_pointer.exists() else None, original_quick_pointer)

    def test_quick_forecast_p2_does_not_create_modify_or_publish_lifecycle_assignments(self):
        runtime_root = _create_p2_v2_assignment(self.test_dir, ROOT, model_id="extra_trees")
        assignments_dir = runtime_root / "model-assignments"
        latest_pointer = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"

        initial_assignments = set(assignments_dir.glob("*"))
        initial_pointer_bytes = latest_pointer.read_bytes()

        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)
        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        result = execute(args)
        self.assertTrue(result["committed"])

        final_assignments = set(assignments_dir.glob("*"))
        final_pointer_bytes = latest_pointer.read_bytes()

        self.assertEqual(initial_assignments, final_assignments)
        self.assertEqual(initial_pointer_bytes, final_pointer_bytes)

    def test_historical_quick_forecast_p1_remains_unchanged_and_readable(self):
        runtime_root = self.test_dir / "p1_runtime"
        workspace_dir, dataset_id, val_sha = build_ready_workspace(runtime_root)

        job, job_file, staging_dir = _setup_quick_run_job(
            runtime_root, workspace_dir.name, dataset_id, val_sha
        )

        args = SimpleNamespace(
            runtime_root=str(runtime_root),
            job_record=str(job_file),
            workspace=str(workspace_dir),
            staging=str(staging_dir)
        )

        p1_policy, p1_policy_hash = load_and_validate_quick_forecast_policy("dhaka_south")
        job.update({
            "policyId": p1_policy["policy_id"],
            "policyVersion": p1_policy["policy_version"],
            "policySha256": p1_policy_hash,
        })
        atomic_json(job_file, job)

        with patch(
            "runtime_quick_forecast._load_quick_forecast_policy",
            return_value=(p1_policy, p1_policy_hash, False),
        ):
            result = execute(args)
        self.assertTrue(result["committed"])

        committed_run = runtime_root / "runs" / job["runId"]
        forecast_output = json.loads((committed_run / "artifacts/forecast_output.json").read_text(encoding="utf-8"))
        calibration = json.loads((committed_run / "artifacts/forecast_calibration.json").read_text(encoding="utf-8"))
        uncertainty = json.loads((committed_run / "artifacts/forecast_uncertainty.json").read_text(encoding="utf-8"))
        model_card = json.loads((committed_run / "artifacts/model_card.json").read_text(encoding="utf-8"))

        self.assertEqual(forecast_output["activeModelId"], "random_forest")
        self.assertEqual(calibration["schemaVersion"], "1.0")
        self.assertEqual(calibration["policyVersion"], "p1.4f-v1")
        self.assertEqual(calibration["calibrationStatus"], "available")
        self.assertEqual(calibration["residualCount"], 68)
        self.assertEqual(len(calibration["folds"]), 68)
        for artifact in (forecast_output, uncertainty, model_card):
            self.assertNotIn("sourceFamily", artifact)
            self.assertNotIn("assignmentId", artifact)
            self.assertNotIn("assignmentCommitSha256", artifact)
        self.assertNotIn("forecastPresentationMode", uncertainty)
        self.assertNotIn("calibrationStatus", uncertainty)
        self.assertNotIn("uncertaintyReasonCode", uncertainty)


if __name__ == "__main__":
    unittest.main()
