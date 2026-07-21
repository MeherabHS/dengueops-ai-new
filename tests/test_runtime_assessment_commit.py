import hashlib
import json
import shutil
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_assessment_commit import RuntimeAssessmentCommitError, commit_runtime_assessment
from runtime_assessment_policy import load_and_validate_assessment_policy
from runtime_validate import validate
from runtime_worker import run_once


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_ready_assessment_runtime(
    base: Path,
    source_rows: int | None = None,
    assessment_policy_version: str | None = None,
):
    runtime = (base / "runtime").resolve()
    workspace_id, job_id, assessment_id = (str(uuid.uuid4()) for _ in range(3))
    workspace = runtime / "workspaces" / workspace_id
    for relative in ("metadata", "inputs/original", "inputs/canonical", "logs"):
        (workspace / relative).mkdir(parents=True, exist_ok=True)
    for relative in ("jobs/running", "jobs/pending", "jobs/completed", "jobs/failed", "assessment-staging", "assessments", "staging", "runs", "deployments", "locks"):
        (runtime / relative).mkdir(parents=True, exist_ok=True)
    dengue = workspace / "inputs/original/dengue.csv"
    climate = workspace / "inputs/original/climate.csv"
    if source_rows is None:
        shutil.copy2(ROOT / "data/dengue_cases.csv", dengue)
        shutil.copy2(ROOT / "data/climate_data.csv", climate)
    else:
        dengue.write_bytes(b"".join((ROOT / "data/dengue_cases.csv").read_bytes().splitlines(keepends=True)[:source_rows + 1]))
        climate.write_bytes(b"".join((ROOT / "data/climate_data.csv").read_bytes().splitlines(keepends=True)[:source_rows + 1]))
    created = iso_now()
    result = validate(SimpleNamespace(workspace_root=str(workspace), workspace_id=workspace_id, created_at=created,
        dengue_input=str(dengue), climate_input=str(climate), canonical_dengue_output=str(workspace / "inputs/canonical/dengue_cases.csv"),
        canonical_climate_output=str(workspace / "inputs/canonical/climate_data.csv"), validation_output=str(workspace / "metadata/validation.json"),
        deployment_id="dhaka_south", workflow_mode="assess_dataset"))
    assert result["eligibility"]["assessDataset"]["assessmentStatus"] == "full_assessment_eligible"
    metadata = {"schemaVersion":"1.0","workspaceId":workspace_id,"correlationId":str(uuid.uuid4()),"deploymentId":"dhaka_south",
        "workflowMode":"assess_dataset","status":"ready","createdAt":created,"updatedAt":iso_now(),"originalFiles":{},"datasetId":result["datasetId"]}
    (workspace / "metadata/workspace.json").write_text(json.dumps(metadata), encoding="utf-8")
    validation_hash = hashlib.sha256((workspace / "metadata/validation.json").read_bytes()).hexdigest()
    policy, policy_hash = load_and_validate_assessment_policy("dhaka_south", assessment_policy_version)
    registry_name = "candidate_models.json" if policy["policy_version"] == "p2-v2" else "candidate_models_p1.2a-v1.json"
    registry_hash = hashlib.sha256((ROOT / "config" / registry_name).read_bytes()).hexdigest()
    job = {"schemaVersion":"1.0","jobKind":"dataset_assessment","jobId":job_id,"assessmentId":assessment_id,"workspaceId":workspace_id,
        "datasetId":result["datasetId"],"deploymentId":"dhaka_south","workflowMode":"assess_dataset","validationRecordSha256":validation_hash,
        "assessmentPolicyId":policy["policy_id"],"assessmentPolicyVersion":policy["policy_version"],"assessmentPolicySha256":policy_hash,
        "candidateRegistrySha256":registry_hash,"status":"queued","progress":"queued","createdAt":created,"claimedAt":None,"startedAt":None,
        "updatedAt":created,"completedAt":None,"heartbeatAt":None,"workerId":None,"processId":None,"timeoutSeconds":1800,"retryCount":0,
        "error":None,"committedAssessmentId":None}
    job_path = runtime / "jobs/pending" / f"{job_id}.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    return runtime, workspace, job_path, job


class RuntimeAssessmentCommitTests(unittest.TestCase):
    def test_archived_phase_one_policy_still_produces_and_validates_historical_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _workspace, pending, job = build_ready_assessment_runtime(
                Path(directory), assessment_policy_version="p1.4d-1-v1"
            )
            self.assertTrue(run_once(runtime, "phase-one-compatibility-worker"))
            completed = runtime / "jobs/completed" / pending.name
            failed = runtime / "jobs/failed" / pending.name
            self.assertTrue(completed.exists(), failed.read_text(errors="replace") if failed.exists() else "")
            committed = runtime / "assessments" / job["assessmentId"]
            rolling = json.loads((committed / "artifacts/rolling_validation.json").read_text())
            commit = json.loads((committed / "metadata/commit.json").read_text())
            self.assertEqual(rolling["schemaVersion"], "1.0")
            self.assertEqual(rolling["assessmentPolicy"]["policyVersion"], "p1.4d-1-v1")
            self.assertEqual(rolling["plannedFoldCount"], 68)
            self.assertNotIn("labelledRows", rolling)
            self.assertEqual(commit["schemaVersion"], "1.0")
            self.assertNotIn("assessmentPolicyVersion", commit)

    def test_minimum_history_commits_common_52_fold_plan_for_all_candidates(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, _workspace, pending, job = build_ready_assessment_runtime(Path(directory), source_rows=164)
            self.assertTrue(run_once(runtime, "minimum-assessment-test-worker"))
            completed = runtime / "jobs/completed" / pending.name
            failed = runtime / "jobs/failed" / pending.name
            self.assertTrue(completed.exists(), failed.read_text(errors="replace") if failed.exists() else "")
            committed = runtime / "assessments" / job["assessmentId"]
            rolling = json.loads((committed / "artifacts/rolling_validation.json").read_text())
            comparison = json.loads((committed / "artifacts/candidate_model_comparison.json").read_text())
            self.assertEqual(rolling["labelledRows"], 157)
            self.assertEqual(rolling["availableFoldCount"], 52)
            self.assertEqual(rolling["plannedFoldCount"], 52)
            self.assertFalse(rolling["foldCapApplied"])
            self.assertEqual(len(rolling["folds"]), 52)
            self.assertEqual([fold["sequence"] for fold in rolling["folds"]], list(range(1, 53)))
            self.assertTrue(all(len(fold["predictions"]) == 10 for fold in rolling["folds"]))
            expected_targets = [fold["actualTarget"] for fold in rolling["folds"]]
            for model_id in rolling["candidateIds"]:
                records = [next(item for item in fold["predictions"] if item["modelId"] == model_id) for fold in rolling["folds"]]
                self.assertEqual(len(records), 52)
                self.assertEqual(
                    [fold["actualTarget"] for fold in rolling["folds"]],
                    expected_targets,
                )
            self.assertEqual(comparison["plannedFoldCount"], 52)
            self.assertEqual({candidate["foldPlanSha256"] for candidate in comparison["candidates"]}, {rolling["foldPlanSha256"]})
            self.assertEqual(
                {candidate["status"] for candidate in comparison["candidates"] if candidate["candidateClass"] == "comparison_baseline"},
                {"baseline_only"},
            )
            winner = next(candidate for candidate in comparison["candidates"] if candidate["status"] == "technical_winner")
            self.assertEqual(winner["modelId"], comparison["technicalWinnerModelId"])
            self.assertEqual(winner["candidateClass"], "learned_model")
            self.assertIn("best-performing eligible learned model within this governed assessment", comparison["selectionReason"])
            self.assertTrue(all(candidate["plannedFolds"] == 52 for candidate in comparison["candidates"]))

    def test_worker_commits_direct_ten_candidate_assessment_without_latest(self):
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        with tempfile.TemporaryDirectory() as directory:
            runtime, _workspace, pending, job = build_ready_assessment_runtime(Path(directory))
            self.assertTrue(run_once(runtime, "assessment-test-worker"))
            completed = runtime / "jobs/completed" / pending.name
            failed = runtime / "jobs/failed" / pending.name
            diagnostics = failed.read_text(errors="replace") if failed.exists() else ""
            for path in runtime.glob("assessment-staging*/**/stderr.log"):
                diagnostics += path.read_text(errors="replace")
            self.assertTrue(completed.exists(), diagnostics)
            completed_job = json.loads(completed.read_text())
            self.assertEqual(completed_job["committedAssessmentId"], job["assessmentId"])
            committed = runtime / "assessments" / job["assessmentId"]
            rolling = json.loads((committed / "artifacts/rolling_validation.json").read_text())
            comparison = json.loads((committed / "artifacts/candidate_model_comparison.json").read_text())
            recommendation = json.loads((committed / "artifacts/recommendation.json").read_text())
            self.assertEqual(len(rolling["folds"]), 68)
            self.assertTrue(all(len(fold["predictions"]) == 10 for fold in rolling["folds"]))
            expected_targets = [fold["actualTarget"] for fold in rolling["folds"]]
            for model_id in rolling["candidateIds"]:
                model_records = [next(item for item in fold["predictions"] if item["modelId"] == model_id) for fold in rolling["folds"]]
                self.assertEqual(len(model_records), len(expected_targets))
            self.assertEqual({fold["featureOrderSha256"] for fold in rolling["folds"]}, {rolling["featureOrderSha256"]})
            gbr = next(value for value in comparison["candidates"] if value["modelId"] == "gradient_boosting")
            self.assertEqual(gbr["executionMode"], "fitted_per_fold")
            self.assertFalse(gbr["historicalPredictionsReused"])
            self.assertEqual(recommendation["recommendationStatus"], "evidence_only")
            self.assertEqual(recommendation["recommendationStrength"], "not_available")
            self.assertFalse(recommendation["approvalEnabled"])
            self.assertFalse((runtime / "deployments/dhaka_south/latest.json").exists())
            for prohibited in ("forecast_output.json","forecast_uncertainty.json","model_card.json","dashboard_summary.json","directives.json"):
                self.assertFalse((committed / "artifacts" / prohibited).exists())

            def json_file(staging, relative):
                path = staging / relative
                return path, json.loads(path.read_text())

            def write(path, value):
                path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

            def rolling_value(staging):
                return json_file(staging, "artifacts/rolling_validation.json")

            def mutate_prediction(field, delta=1.0):
                def mutate(staging):
                    path, value = rolling_value(staging)
                    record = value["folds"][0]["predictions"][0]
                    record[field] = float(record[field]) + delta
                    write(path, value)
                return mutate

            def mutate_metric(field):
                def mutate(staging):
                    comparison_path, comparison_value = json_file(staging, "artifacts/candidate_model_comparison.json")
                    summary_path, summary_value = json_file(staging, "artifacts/assessment_summary.json")
                    comparison_value["candidates"][0]["metrics"][field] += 1.0
                    summary_value["candidates"][0]["metrics"][field] += 1.0
                    write(comparison_path, comparison_value); write(summary_path, summary_value)
                return mutate

            def mutate_count(field):
                def mutate(staging):
                    comparison_path, comparison_value = json_file(staging, "artifacts/candidate_model_comparison.json")
                    summary_path, summary_value = json_file(staging, "artifacts/assessment_summary.json")
                    comparison_value["candidates"][0][field] += 1
                    summary_value["candidates"][0][field] += 1
                    write(comparison_path, comparison_value); write(summary_path, summary_value)
                return mutate

            def mutate_actual(staging):
                path, value = rolling_value(staging); value["folds"][0]["actualTarget"] += 1.0; write(path, value)

            def mutate_fold_hash(staging):
                path, value = rolling_value(staging); value["foldPlanSha256"] = "0" * 64; write(path, value)

            def mutate_fold_order(staging):
                path, value = rolling_value(staging); value["folds"][0], value["folds"][1] = value["folds"][1], value["folds"][0]; write(path, value)

            def mutate_rolling_field(field, value):
                def mutate(staging):
                    path, rolling = rolling_value(staging); rolling[field] = value; write(path, rolling)
                return mutate

            def mutate_training_count(staging):
                path, value = rolling_value(staging); value["folds"][0]["trainingRowCount"] += 1; write(path, value)

            def omit_recent_fold(staging):
                path, value = rolling_value(staging); value["folds"].pop(); value["plannedFoldCount"] = 67; write(path, value)

            def substitute_older_fold(staging):
                path, value = rolling_value(staging)
                value["folds"][-1] = json.loads(json.dumps(value["folds"][0]))
                value["folds"][-1]["sequence"] = 68
                write(path, value)

            def mutate_policy_version(staging):
                path, value = rolling_value(staging); value["assessmentPolicy"]["policyVersion"] = "p1.4d-1-v1"; write(path, value)

            def mutate_policy_hash(staging):
                path, value = rolling_value(staging); value["assessmentPolicy"]["policySha256"] = "0" * 64; write(path, value)

            def mutate_eligibility(staging):
                comparison_path, comparison_value = json_file(staging, "artifacts/candidate_model_comparison.json")
                summary_path, summary_value = json_file(staging, "artifacts/assessment_summary.json")
                comparison_value["candidates"][0]["selectionEligible"] = False
                summary_value["candidates"][0]["selectionEligible"] = False
                write(comparison_path, comparison_value); write(summary_path, summary_value)

            def mutate_winner(staging):
                comparison_path, comparison_value = json_file(staging, "artifacts/candidate_model_comparison.json")
                summary_path, summary_value = json_file(staging, "artifacts/assessment_summary.json")
                recommendation_path, recommendation_value = json_file(staging, "artifacts/recommendation.json")
                replacement = next(candidate for candidate in comparison_value["candidates"] if candidate["modelId"] != comparison_value["technicalWinnerModelId"] and candidate["selectionEligible"])
                comparison_value["technicalWinnerModelId"] = replacement["modelId"]
                comparison_value["winnerParameterSha256"] = replacement["parametersSha256"]
                summary_value["technicalWinnerModelId"] = replacement["modelId"]
                recommendation_value["technicalWinnerModelId"] = replacement["modelId"]
                recommendation_value["winnerParameterSha256"] = replacement["parametersSha256"]
                write(comparison_path, comparison_value); write(summary_path, summary_value); write(recommendation_path, recommendation_value)

            def mutate_summary_only(staging):
                path, value = json_file(staging, "artifacts/assessment_summary.json"); value["candidates"][0]["modelLabel"] = "tampered"; write(path, value)

            def mutate_nonstandard(constant):
                def mutate(staging):
                    path = staging / "artifacts/rolling_validation.json"
                    value = json.loads(path.read_text()); value["folds"][0]["predictions"][0]["rawPrediction"] = constant
                    path.write_text(json.dumps(value, allow_nan=True), encoding="utf-8")
                return mutate

            tampering = {
                "raw_prediction": mutate_prediction("rawPrediction"), "published_prediction": mutate_prediction("publishedPrediction"),
                "actual_target": mutate_actual, "signed_error": mutate_prediction("signedError"), "absolute_error": mutate_prediction("absoluteError"),
                "squared_error": mutate_prediction("squaredError"), "mae": mutate_metric("mae"), "rmse": mutate_metric("rmse"),
                "wape": mutate_metric("wape"), "median": mutate_metric("medianAbsoluteError"), "maximum": mutate_metric("maximumAbsoluteError"),
                "successful_count": mutate_count("successfulFolds"), "failed_count": mutate_count("failedFolds"),
                "fold_hash": mutate_fold_hash, "fold_order": mutate_fold_order, "eligibility": mutate_eligibility,
                "available_fold_count": mutate_rolling_field("availableFoldCount", 69),
                "planned_fold_count": mutate_rolling_field("plannedFoldCount", 67),
                "fold_cap_status": mutate_rolling_field("foldCapApplied", True),
                "selected_start_index": mutate_rolling_field("selectedValidationStartIndex", 106),
                "selected_end_index": mutate_rolling_field("selectedValidationEndIndex", 171),
                "training_row_count": mutate_training_count,
                "omitted_recent_fold": omit_recent_fold,
                "substituted_older_fold": substitute_older_fold,
                "policy_version": mutate_policy_version,
                "policy_hash": mutate_policy_hash,
                "winner": mutate_winner, "summary_mismatch": mutate_summary_only,
                "nan": mutate_nonstandard(float("nan")), "infinity": mutate_nonstandard(float("inf")), "negative_infinity": mutate_nonstandard(float("-inf")),
            }
            for name, mutate in tampering.items():
                with self.subTest(tampering=name):
                    case_root = (Path(directory) / f"tamper-{name}").resolve()
                    staging = case_root / "assessment-staging" / job["assessmentId"]
                    staging.parent.mkdir(parents=True)
                    shutil.copytree(committed, staging, copy_function=shutil.copyfile)
                    mutate(staging)
                    with self.assertRaises(RuntimeAssessmentCommitError):
                        commit_runtime_assessment(case_root, staging, job)
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_incomplete_bundle_cannot_commit_or_create_latest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            assessment_id = str(uuid.uuid4())
            staging = root / "assessment-staging" / assessment_id
            (staging / "artifacts").mkdir(parents=True)
            job = {"assessmentId":assessment_id,"jobId":str(uuid.uuid4()),"workspaceId":str(uuid.uuid4()),"datasetId":"a"*64,
                "deploymentId":"dhaka_south","validationRecordSha256":"b"*64,"assessmentPolicySha256":"c"*64,"candidateRegistrySha256":"d"*64}
            with self.assertRaises(RuntimeAssessmentCommitError):
                commit_runtime_assessment(root, staging, job)
            self.assertFalse((root / "deployments/dhaka_south/latest.json").exists())


if __name__ == "__main__":
    unittest.main()
