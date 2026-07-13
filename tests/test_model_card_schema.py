from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from deployment_profiles import (  # noqa: E402
    DeploymentProfileError, load_deployment_profile, validate_model_card_against_profile,
)
from provenance import artifact_provenance, assert_same_provenance  # noqa: E402


class ModelCardSchemaTest(unittest.TestCase):
    def setUp(self):
        self.profile = load_deployment_profile("dhaka_south")
        self.card = json.loads((ROOT / "data" / "model_card.json").read_text(encoding="utf-8"))

    def test_generated_benchmark_card_passes_and_has_mandatory_limits(self):
        validate_model_card_against_profile(self.card, self.profile)
        self.assertEqual(self.card["selected_features"], self.profile["selected_features"])
        self.assertEqual(len(self.card["selected_features"]), 18)
        text = " ".join(self.card["limitations"])
        for expected in ("deterministic synthetic benchmark data", "legacy chronological holdout", "not a prediction interval", "No local calibration", "not for clinical or official public-health use"):
            self.assertIn(expected, text)
        self.assertEqual(self.card["explainability_status"], "generated")
        self.assertEqual(self.card["explainability_evaluation"]["estimator_role"], "selected_model_chronological_holdout_validation_instance")
        self.assertIn("does not establish causality", " ".join(self.card["explainability_limitations"]))

    def test_identity_and_hash_mismatches_fail(self):
        for key, value in (("deployment_id", "other"), ("formula_registry_sha256", "0" * 64), ("deployment_profile_sha256", "0" * 64), ("evidence_registry_sha256", "0" * 64)):
            card = copy.deepcopy(self.card); card[key] = value
            with self.subTest(key=key), self.assertRaises(DeploymentProfileError):
                validate_model_card_against_profile(card, self.profile)

    def test_required_library_version_and_training_period(self):
        for key in ("estimator_library_version", "training_period"):
            card = copy.deepcopy(self.card); del card[key]
            with self.subTest(key=key), self.assertRaisesRegex(DeploymentProfileError, "schema"):
                validate_model_card_against_profile(card, self.profile)

    def test_gate_approval_inconsistency_fails(self):
        card = copy.deepcopy(self.card); card["deployment_gate"] = "operational_advisory"
        with self.assertRaises(DeploymentProfileError):
            validate_model_card_against_profile(card, self.profile)

    def test_all_profiled_artifacts_share_governance_provenance(self):
        names = ["validation_metrics.json", "forecast_output.json", "directives.json", "dashboard_summary.json", "pipeline_run_summary.json", "model_comparison.json", "chart_data.json", "model_card.json", "model_explainability.json"]
        values = [json.loads((ROOT / "data" / name).read_text(encoding="utf-8")) for name in names]
        provenance = [artifact_provenance(value, name) for value, name in zip(values, names)]
        shared = assert_same_provenance(*provenance, labels=names)
        self.assertEqual(len({item["run_id"] for item in provenance}), 1)
        for key in ("manifest_sha256", "formula_registry_sha256", "deployment_profile_sha256", "evidence_registry_sha256", "model_card_id", "model_card_version"):
            self.assertEqual(len({item[key] for item in provenance}), 1)
        self.assertNotIn("run_id", self.card.keys())
        altered = copy.deepcopy(shared); altered["deployment_profile_sha256"] = "0" * 64
        with self.assertRaises(Exception):
            assert_same_provenance(shared, altered)


if __name__ == "__main__":
    unittest.main()
