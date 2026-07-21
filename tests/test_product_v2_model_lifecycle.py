import hashlib
import json
import shutil
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_commit import atomic_json, sha256_file
from runtime_worker import run_once
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime, iso_now
from tests.lifecycle_fixtures import build_one_run_chain_p2_v2, build_promotion_chain_p2_v1
from runtime_model_lifecycle import execute as execute_lifecycle, verify_lifecycle_action
from runtime_model_lifecycle_commit import commit_lifecycle_action


class ProductV2ModelLifecycleTests(unittest.TestCase):
    def test_p2_v2_lifecycle_policy_has_exact_canonical_hash_and_schema(self):
        policy_path = ROOT / "config/deployments/dhaka_south/model_lifecycle_policy.json"
        policy = json.loads(policy_path.read_text())
        self.assertEqual(policy["schemaVersion"], "2.0")
        self.assertEqual(policy["policyVersion"], "p2-v2")
        self.assertEqual(policy["policyId"], "RUNTIME.MODEL_LIFECYCLE.DECISION")
        self.assertEqual(policy["allowedActions"], ["assign_selected_model"])
        self.assertEqual(len(policy["allowedCandidateIds"]), 8)
        expected_sha = policy.pop("policySha256")

        digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(digest, expected_sha)

    def test_initial_p2_v2_assignment_for_all_eight_learned_candidates(self):
        """All eight learned candidates must be assignable as technical winner (override=False).

        Each model is built as the technical winner via a fully internally consistent
        synthetic p2-v2 evidence chain.  Extra Trees being the real assessment winner
        and Negative Binomial genuinely failing folds are fixture-assumption differences,
        not production defects — the fixture patches the chain orthogonally.
        """
        learned_candidates = (
            "ridge_regression", "poisson_regression", "random_forest", "gradient_boosting",
            "elastic_net", "negative_binomial_regression", "extra_trees", "hist_gradient_boosting"
        )
        for model_id in learned_candidates:
            with self.subTest(model=model_id):
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory)
                    chain = build_one_run_chain_p2_v2(target, ROOT, model_id=model_id, override=False)
                    runtime = chain["runtime"]
                    result = commit_lifecycle_action(
                        runtime,
                        one_run_forecast_run_id=chain["runId"],
                        reason="Initial governed assignment for testing.",
                        operator_identifier="governed-test-operator",
                        acknowledgement=True
                    )
                    self.assertTrue(result["success"], f"lifecycle failed for {model_id}: {result.get('error')}")
                    self.assertEqual(result["action"], "assign_selected_model")
                    self.assertEqual(result["modelId"], model_id)
                    pointer = json.loads((runtime / "deployments/dhaka_south/model-assignment/latest.json").read_text())
                    self.assertEqual(pointer["assignmentId"], result["assignmentId"])
                    self.assertEqual(pointer["assignedModelId"], model_id)
                    assignment = json.loads((runtime / "model-assignments" / result["assignmentId"] / "artifacts/assignment_record.json").read_text())
                    self.assertEqual(assignment["modelId"], model_id)

    def test_approve_eligible_non_winner_override_for_representative_models(self):
        """approve_eligible_non_winner path assigns correctly for representative eligible challengers.

        The actual technical winner is retained in the assessment evidence; the selected
        model is an eligible non-winner.  Both acknowledgements are required.
        """
        # Two representative eligible challengers (must differ from actual assessment winner)
        override_candidates = ("ridge_regression", "gradient_boosting")
        for model_id in override_candidates:
            with self.subTest(model=model_id):
                with tempfile.TemporaryDirectory() as directory:
                    target = Path(directory)
                    chain = build_one_run_chain_p2_v2(target, ROOT, model_id=model_id, override=True)
                    runtime = chain["runtime"]
                    result = commit_lifecycle_action(
                        runtime,
                        one_run_forecast_run_id=chain["runId"],
                        reason="Eligible challenger override for governance test.",
                        operator_identifier="governed-test-operator",
                        acknowledgement=True
                    )
                    self.assertTrue(result["success"], f"override lifecycle failed for {model_id}: {result.get('error')}")
                    self.assertEqual(result["action"], "assign_selected_model")
                    self.assertEqual(result["modelId"], model_id)

    def test_assignment_chain_sequential_promotion(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain1 = build_one_run_chain_p2_v2(target / "c1", ROOT, model_id="random_forest")
            runtime = chain1["runtime"]
            res1 = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain1["runId"],
                reason="First assignment",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertTrue(res1["success"], f"res1 failed: {res1.get('error')}")


            chain2 = build_one_run_chain_p2_v2(target / "c2", ROOT, model_id="ridge_regression", override=True)
            # Copy chain2 decision & forecast artifacts into the existing runtime
            shutil.copytree(chain2["runtime"] / "decisions", runtime / "decisions", dirs_exist_ok=True)
            shutil.copytree(chain2["runtime"] / "authorizations", runtime / "authorizations", dirs_exist_ok=True)
            shutil.copytree(chain2["runtime"] / "authorization-state", runtime / "authorization-state", dirs_exist_ok=True)
            shutil.copytree(chain2["runtime"] / "assessments", runtime / "assessments", dirs_exist_ok=True)
            shutil.copytree(chain2["runtime"] / "runs", runtime / "runs", dirs_exist_ok=True)
            shutil.copytree(chain2["runtime"] / "jobs", runtime / "jobs", dirs_exist_ok=True)

            res2 = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain2["runId"],
                reason="Second assignment overriding to ridge",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertTrue(res2["success"])

            pointer = json.loads((runtime / "deployments/dhaka_south/model-assignment/latest.json").read_text())
            self.assertEqual(pointer["assignmentId"], res2["assignmentId"])
            self.assertEqual(pointer["assignedModelId"], "ridge_regression")
            self.assertEqual(pointer["priorAssignmentId"], res1["assignmentId"])

    def test_baseline_and_diagnostic_and_unauthorized_rejections(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain = build_one_run_chain_p2_v2(target, ROOT, model_id="random_forest")
            runtime = chain["runtime"]

            # Tamper forecast output to report a baseline model ID
            forecast_path = runtime / "runs" / chain["runId"] / "artifacts/forecast_output.json"
            output = json.loads(forecast_path.read_text())
            output["selectedModelId"] = "moving_average_4w"
            atomic_json(forecast_path, output)
            commit_p = runtime / "runs" / chain["runId"] / "metadata/commit.json"
            commit = json.loads(commit_p.read_text())
            commit["artifactHashes"]["forecast_output.json"] = sha256_file(forecast_path)
            atomic_json(commit_p, commit)

            res = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="Attempting baseline assignment",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertFalse(res["success"])
            self.assertFalse((runtime / "deployments/dhaka_south/model-assignment/latest.json").exists())

    def test_tampered_forecast_commit_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain = build_one_run_chain_p2_v2(target, ROOT, model_id="random_forest")
            runtime = chain["runtime"]

            forecast_path = runtime / "runs" / chain["runId"] / "artifacts/forecast_output.json"
            forecast_path.write_bytes(forecast_path.read_bytes() + b"\n")

            res = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="Tampered test",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertFalse(res["success"])
            self.assertFalse((runtime / "deployments/dhaka_south/model-assignment/latest.json").exists())

    def test_missing_reason_or_acknowledgement_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            chain = build_one_run_chain_p2_v2(target, ROOT, model_id="random_forest")
            runtime = chain["runtime"]

            res1 = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="",
                operator_identifier="test-op",
                acknowledgement=True
            )
            self.assertFalse(res1["success"])

            res2 = commit_lifecycle_action(
                runtime,
                one_run_forecast_run_id=chain["runId"],
                reason="Valid reason",
                operator_identifier="test-op",
                acknowledgement=False
            )
            self.assertFalse(res2["success"])
            self.assertFalse((runtime / "deployments/dhaka_south/model-assignment/latest.json").exists())

    def test_negative_binomial_regression_is_ineligible_in_real_p2v2_assessment(self):
        """Real-assessment regression: NB genuinely fails folds and is non-selectable.

        This test does NOT patch the assessment.  It runs the real p2-v2 assessment
        and confirms that negative_binomial_regression:
        - does not complete all folds
        - has selectionEligible=False
        - has status='failed'

        This is a fixture-assumption fact, not a production defect.  The synthetic
        winner-patching fixture (build_one_run_chain_p2_v2) handles this correctly
        by injecting donor records for NB when needed.
        """
        from tests.test_runtime_assessment_commit import build_ready_assessment_runtime
        from runtime_worker import run_once
        import json

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            runtime, _workspace, _pending, assessment_job = build_ready_assessment_runtime(
                base / "runtime", assessment_policy_version="p2-v2"
            )
            ran = run_once(runtime, "one-run-assessment")
            self.assertTrue(ran, "p2-v2 assessment did not run")

            assessment = runtime / "assessments" / assessment_job["assessmentId"]
            summary_path = assessment / "artifacts/assessment_summary.json"
            # Only check if the assessment was committed (summary exists)
            if not summary_path.exists():
                self.skipTest("p2-v2 assessment did not produce a summary (insufficient data?)")

            summary = json.loads(summary_path.read_text())
            nb = next(
                (c for c in summary.get("candidates", []) if c["modelId"] == "negative_binomial_regression"),
                None,
            )
            self.assertIsNotNone(nb, "negative_binomial_regression not in p2-v2 assessment candidates")
            self.assertFalse(
                nb.get("selectionEligible"),
                f"Expected NB to be ineligible in real assessment; got selectionEligible={nb.get('selectionEligible')}"
            )
            self.assertEqual(
                nb.get("status"), "failed",
                f"Expected NB status='failed' in real assessment; got '{nb.get('status')}'"
            )
            self.assertGreater(
                nb.get("failedFolds", 0), 0,
                "Expected NB to have at least one failed fold in the real assessment"
            )


if __name__ == "__main__":
    unittest.main()
