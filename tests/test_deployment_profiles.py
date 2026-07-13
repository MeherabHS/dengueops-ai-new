from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from deployment_profiles import (  # noqa: E402
    DeploymentProfileError, load_deployment_profile, resolve_profile_run_configuration,
    validate_deployment_profile,
)
from run_pipeline import run_pipeline  # noqa: E402


class DeploymentProfileTest(unittest.TestCase):
    def setUp(self):
        self.profile = load_deployment_profile("dhaka_south")

    def assert_invalid(self, mutate, message=None):
        value = copy.deepcopy(self.profile); mutate(value)
        context = self.assertRaisesRegex(DeploymentProfileError, message) if message else self.assertRaises(DeploymentProfileError)
        with context:
            validate_deployment_profile(value)

    def test_dhaka_south_profile_passes(self):
        self.assertEqual(self.profile["deployment_gate"], "benchmark_only")
        self.assertEqual(self.profile["observed_data_mode"], "synthetic")
        self.assertEqual(self.profile["evidence_ids"], [])

    def test_unknown_profile_and_path_traversal_fail(self):
        with self.assertRaisesRegex(DeploymentProfileError, "Unknown"):
            load_deployment_profile("missing_profile")
        for value in ("../dhaka_south", "dhaka/south", ".."):
            with self.subTest(value=value), self.assertRaises(DeploymentProfileError):
                load_deployment_profile(value)

    def test_unknown_profile_fails_before_producer(self):
        with patch("run_pipeline.run_step") as run_step:
            self.assertEqual(run_pipeline(deployment_profile="missing_profile"), 2)
            run_step.assert_not_called()

    def test_registry_hash_mismatches_fail(self):
        self.assert_invalid(lambda p: p.__setitem__("formula_registry_sha256", "0" * 64), "Formula-registry hash")
        self.assert_invalid(lambda p: p.__setitem__("evidence_registry_sha256", "0" * 64), "Evidence-registry hash")

    def test_unknown_source_and_formula_ids_fail(self):
        self.assert_invalid(lambda p: p["data_sources"]["cases"].__setitem__("source_id", "unknown"), "Unknown cases source")
        self.assert_invalid(lambda p: p["formula_ids"].append("UNKNOWN.FORMULA"), "Unknown formula")

    def test_cli_profile_conflicts_fail(self):
        for key, value in (("case_source", "opendengue"), ("deployment_gate", "operational_advisory")):
            with self.subTest(key=key), self.assertRaisesRegex(DeploymentProfileError, "conflicts"):
                resolve_profile_run_configuration(self.profile, {key: value})

    def test_partial_benchmark_selection_fails(self):
        self.assert_invalid(lambda p: p["data_sources"]["cases"].__setitem__("source_id", "synthetic_demo"), "benchmark")

    def test_synthetic_local_claim_and_high_gate_fail(self):
        self.assert_invalid(lambda p: p.__setitem__("data_mode", "locally_calibrated_deployment"))
        self.assert_invalid(lambda p: p.__setitem__("deployment_gate", "research_candidate"), "formula maximum|benchmark")

    def test_approval_and_shadow_rules_fail_closed(self):
        self.assert_invalid(lambda p: p.__setitem__("deployment_gate", "institution_approved"), "approval")
        self.assert_invalid(lambda p: p.__setitem__("deployment_gate", "shadow_validated"), "shadow|approval")

    def test_invalid_timezone_dates_and_retired_status_fail(self):
        self.assert_invalid(lambda p: p.__setitem__("timezone", "Mars/Dhaka"), "timezone")
        self.assert_invalid(lambda p: p.__setitem__("review_date", "2020-01-01"), "effective_date")
        self.assert_invalid(lambda p: p.__setitem__("status", "retired"), "cannot execute")


if __name__ == "__main__":
    unittest.main()
