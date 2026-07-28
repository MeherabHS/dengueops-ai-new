import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(ROOT / "analytics"))

import runtime_model_assignment_cli as cli
from tests.lifecycle_fixtures import build_one_run_chain_p2_v2


class RuntimeModelAssignmentCliTests(unittest.TestCase):
    def arguments(self, runtime: Path, run_id: str) -> argparse.Namespace:
        return argparse.Namespace(
            approved_forecast_run_id=run_id,
            reason="Governed assignment from the verified approved forecast.",
            acknowledgement="true",
            runtime_root=runtime,
            repository_root=ROOT,
            operator_identifier="isolated-super-user",
        )

    def test_cli_is_a_narrow_delegate_and_rejects_model_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            with patch.object(cli, "commit_lifecycle_action", return_value={
                "success": True,
                "assignmentId": "11111111-1111-4111-8111-111111111111",
                "modelId": "poisson_gam",
            }) as delegate:
                result = cli.execute(self.arguments(runtime, "22222222-2222-4222-8222-222222222222"))
            self.assertEqual(result["selectedCandidateId"], "poisson_gam")
            self.assertNotIn("candidateId", result)
            delegate.assert_called_once()
            call = delegate.call_args.kwargs
            self.assertNotIn("model_id", call)
            self.assertEqual(call["operator_identifier"], "isolated-super-user")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = cli.main([
                    "--approved-forecast-run-id", "22222222-2222-4222-8222-222222222222",
                    "--reason", "bounded",
                    "--acknowledgement", "true",
                    "--runtime-root", str(runtime),
                    "--repository-root", str(ROOT),
                    "--operator-identifier", "operator",
                    "--candidate-id", "random_forest",
                ])
            self.assertEqual(exit_code, 2)
            self.assertEqual(json.loads(output.getvalue())["code"], "invalid_assignment_cli_request")

    def test_winner_and_governed_override_publish_atomic_isolated_assignments(self):
        cases = (
            ("extra_trees", False),
            ("random_forest", True),
        )
        for model_id, override in cases:
            with self.subTest(model_id=model_id, override=override), tempfile.TemporaryDirectory() as directory:
                chain = build_one_run_chain_p2_v2(Path(directory), ROOT, model_id=model_id, override=override)
                result = cli.execute(self.arguments(chain["runtime"], chain["runId"]))
                self.assertTrue(result["ok"], result)
                self.assertEqual(result["selectedCandidateId"], model_id)
                pointer = chain["runtime"] / "deployments/dhaka_south/model-assignment/latest.json"
                assignment = chain["runtime"] / "model-assignments" / str(result["assignmentId"])
                self.assertTrue(pointer.is_file())
                self.assertTrue((assignment / "artifacts/assignment_record.json").is_file())
                self.assertTrue((assignment / "metadata/commit.json").is_file())

    def test_tamper_failure_preserves_existing_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            chain = build_one_run_chain_p2_v2(base / "valid", ROOT, model_id="extra_trees")
            first = cli.execute(self.arguments(chain["runtime"], chain["runId"]))
            self.assertTrue(first["ok"])
            pointer = chain["runtime"] / "deployments/dhaka_south/model-assignment/latest.json"
            before = pointer.read_bytes()
            commit_path = chain["runtime"] / "runs" / chain["runId"] / "metadata/commit.json"
            commit = json.loads(commit_path.read_text(encoding="utf-8"))
            commit["selectedModelFamily"] = "TamperedFamily"
            commit_path.write_text(json.dumps(commit), encoding="utf-8")
            failed = cli.execute(self.arguments(chain["runtime"], chain["runId"]))
            self.assertFalse(failed["ok"])
            self.assertEqual(pointer.read_bytes(), before)

    def test_invalid_identity_acknowledgement_and_output_are_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            bad = self.arguments(runtime, "33333333-3333-4333-8333-333333333333")
            bad.acknowledgement = "false"
            with patch.object(cli, "commit_lifecycle_action") as delegate:
                with self.assertRaises(ValueError):
                    cli.execute(bad)
                delegate.assert_not_called()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = cli.main(["--approved-forecast-run-id", "not-a-uuid"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue()), {
                "code": "invalid_assignment_cli_request",
                "ok": False,
            })
            self.assertNotIn(str(runtime), output.getvalue())


if __name__ == "__main__":
    unittest.main()
