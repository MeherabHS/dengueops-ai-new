import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "analytics"))

from tests.lifecycle_fixtures import build_one_run_chain_p2_v2, build_promotion_chain_p2_v1
from tests.test_runtime_model_lifecycle import lifecycle_job
from runtime_model_lifecycle import execute as execute_lifecycle
from runtime_model_lifecycle_commit import commit_lifecycle_action
from runtime_active_model import (
    PROFILE_SHA,
    ActiveModelError,
    resolve_active_model,
    resolve_active_model_p2_v2,
    resolve_historical_active_model_p2_v1,
)
from runtime_model_lifecycle_policy import (
    ModelLifecyclePolicyError,
    POLICY_ID,
    POLICY_SHA256,
    canonical_sha256,
    load_current_model_lifecycle_policy,
    load_model_lifecycle_policy,
    load_model_lifecycle_policy_by_identity,
)


class CrossVersionRoutingTests(unittest.TestCase):

    def test_p2_v1_historical_state_resolves_through_archived_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            job, path = lifecycle_job(runtime, expectedProfileSha256=PROFILE_SHA)
            execute_lifecycle(path, runtime, runtime / "lifecycle-staging" / job["lifecycleDecisionId"], ROOT)
            authority = resolve_historical_active_model_p2_v1(repository_root=ROOT, runtime_root=runtime)
            self.assertEqual(authority["authoritySource"], "committed_assignment")
            self.assertEqual(authority["lifecyclePolicyVersion"], "p2-v1")

    def test_p2_v2_assignment_resolves_through_current_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain = build_one_run_chain_p2_v2(target, ROOT, model_id="poisson_regression", override=True)
            runtime = chain["runtime"]
            commit_res = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="Assign poisson_regression",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertTrue(commit_res["success"], f"Commit failed: {commit_res.get('error')}")
            authority = resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime)
            self.assertEqual(authority["authoritySource"], "committed_assignment")
            self.assertEqual(authority["modelId"], "poisson_regression")
            self.assertEqual(authority["policyVersion"], "p2-v2")

    def test_p2_v2_unassigned_with_valid_p2_v1_assignment_present(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            job, path = lifecycle_job(runtime, expectedProfileSha256=PROFILE_SHA)
            execute_lifecycle(path, runtime, runtime / "lifecycle-staging" / job["lifecycleDecisionId"], ROOT)
            # Pointer exists in model-assignment pointing to model-lifecycle
            # p2-v2 resolver must reject pointer or state and throw active_model_not_assigned
            with self.assertRaises(ActiveModelError):
                resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime)

    def test_p2_v2_unassigned_with_historical_profile_fallback_present(self):
        with tempfile.TemporaryDirectory() as directory:
            empty_runtime = Path(directory)
            with self.assertRaises(ActiveModelError) as ctx:
                resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=empty_runtime)
            self.assertIn("active_model_not_assigned", str(ctx.exception))

    def test_both_version_directories_present(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain_v2 = build_one_run_chain_p2_v2(target, ROOT, model_id="random_forest")
            runtime = chain_v2["runtime"]
            commit_res = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain_v2["runId"],
                reason="Assign RF p2-v2",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertTrue(commit_res["success"])

            # Create dummy model-lifecycle directory beside model-assignments
            (runtime / "model-lifecycle/dummy-id").mkdir(parents=True, exist_ok=True)

            authority_v2 = resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime)
            self.assertEqual(authority_v2["authoritySource"], "committed_assignment")
            self.assertEqual(authority_v2["policyVersion"], "p2-v2")

            # Historical resolver rejects p2-v2 pointer
            with self.assertRaises(ActiveModelError) as ctx:
                resolve_historical_active_model_p2_v1(repository_root=ROOT, runtime_root=runtime)

    def test_p2_v2_pointer_referencing_model_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain = build_one_run_chain_p2_v2(target, ROOT, model_id="random_forest")
            runtime = chain["runtime"]
            commit_res = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="Assign RF",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertTrue(commit_res["success"])

            pointer_path = runtime / "deployments/dhaka_south/model-assignment/latest.json"
            pointer = json.loads(pointer_path.read_text())
            pointer["assignmentPath"] = "model-lifecycle/fake-id/artifacts/model_assignment.json"
            pointer_path.write_text(json.dumps(pointer))

            with self.assertRaises(ActiveModelError):
                resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime)

    def test_historical_pointer_referencing_model_assignments(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            job, path = lifecycle_job(runtime, expectedProfileSha256=PROFILE_SHA)
            execute_lifecycle(path, runtime, runtime / "lifecycle-staging" / job["lifecycleDecisionId"], ROOT)

            pointer_path = runtime / "deployments/dhaka_south/model-assignment/latest.json"
            pointer = json.loads(pointer_path.read_text())
            pointer["schemaVersion"] = "2.0"
            pointer_path.write_text(json.dumps(pointer))

            with self.assertRaises(ActiveModelError) as ctx:
                resolve_historical_active_model_p2_v1(repository_root=ROOT, runtime_root=runtime)
            self.assertIn("Cross-version assignment pointer rejected", str(ctx.exception))

    def test_valid_canonical_hash_with_wrong_raw_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            temp_repo = Path(directory) / "repo"
            shutil.copytree(ROOT / "config", temp_repo / "config")

            wrong_raw_sha = "0000000000000000000000000000000000000000000000000000000000000000"
            with self.assertRaises(ModelLifecyclePolicyError) as ctx:
                load_model_lifecycle_policy_by_identity(
                    policy_id=POLICY_ID,
                    policy_version="p2-v1",
                    expected_canonical_sha256=POLICY_SHA256,
                    expected_raw_sha256=wrong_raw_sha,
                    repository_root=temp_repo,
                    deployment_id="dhaka_south"
                )
            self.assertIn("Raw policy SHA-256 mismatch", str(ctx.exception))

    def test_valid_raw_hash_with_wrong_embedded_canonical_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            temp_repo = Path(directory) / "repo"
            shutil.copytree(ROOT / "config", temp_repo / "config")

            policy_file = temp_repo / "config/deployments/dhaka_south/model_lifecycle_policy_p2-v1.json"
            data = json.loads(policy_file.read_text())
            data["policy_sha256"] = "1111111111111111111111111111111111111111111111111111111111111111"
            policy_file.write_text(json.dumps(data))

            with self.assertRaises(ModelLifecyclePolicyError) as ctx:
                load_model_lifecycle_policy(policy_version="p2-v1", repository_root=temp_repo, deployment_id="dhaka_south")
            self.assertIn("Embedded canonical policy hash mismatch", str(ctx.exception))

    def test_policy_at_wrong_repository_path(self):
        with tempfile.TemporaryDirectory() as directory:
            empty_repo = Path(directory) / "empty"
            empty_repo.mkdir()
            with self.assertRaises(ModelLifecyclePolicyError) as ctx:
                load_model_lifecycle_policy(policy_version="p2-v2", repository_root=empty_repo, deployment_id="dhaka_south")
            self.assertIn("Model lifecycle policy file not found", str(ctx.exception))

    def test_unknown_version_passed_to_loader(self):
        with self.assertRaises(ModelLifecyclePolicyError) as ctx:
            load_model_lifecycle_policy(policy_version="unknown_ver", repository_root=ROOT) # type: ignore
        self.assertIn("Unknown or unsupported policy version", str(ctx.exception))

    def test_historical_resolution_remains_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            job, path = lifecycle_job(runtime, expectedProfileSha256=PROFILE_SHA)
            execute_lifecycle(path, runtime, runtime / "lifecycle-staging" / job["lifecycleDecisionId"], ROOT)

            files_before = set(runtime.rglob("*"))
            authority = resolve_historical_active_model_p2_v1(repository_root=ROOT, runtime_root=runtime)
            files_after = set(runtime.rglob("*"))

            self.assertEqual(authority["authoritySource"], "committed_assignment")
            self.assertEqual(files_before, files_after)


    def test_job_missing_policy_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            job, path = lifecycle_job(runtime, expectedProfileSha256=PROFILE_SHA)
            data = json.loads(path.read_text())
            del data["policyVersion"]
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                execute_lifecycle(path, runtime, runtime / "lifecycle-staging" / job["lifecycleDecisionId"], ROOT)

    def test_job_unknown_policy_version_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            job, path = lifecycle_job(runtime, expectedProfileSha256=PROFILE_SHA)
            data = json.loads(path.read_text())
            data["policyVersion"] = "p9-v9"
            path.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                execute_lifecycle(path, runtime, runtime / "lifecycle-staging" / job["lifecycleDecisionId"], ROOT)


    def test_no_implicit_retry_between_versions(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            # Create a p2-v1 assignment
            job, path = lifecycle_job(runtime, expectedProfileSha256=PROFILE_SHA)
            execute_lifecycle(path, runtime, runtime / "lifecycle-staging" / job["lifecycleDecisionId"], ROOT)
            # Calling p2-v2 resolver MUST NOT retry p2-v1 historical resolver
            with self.assertRaises(ActiveModelError):
                resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime)


if __name__ == "__main__":
    unittest.main()

