from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from dashboard_exporter import build_dashboard_summary  # noqa: E402
from explainability_engine import ExplainabilityError, validate_model_explainability  # noqa: E402
from provenance import ProvenanceError, artifact_provenance, assert_same_provenance  # noqa: E402


class ExplainabilityProvenanceTest(unittest.TestCase):
    def test_p11_registry_binding_preserves_p04_semantics(self):
        artifact = json.loads((ROOT / "data" / "model_explainability.json").read_text(encoding="utf-8"))
        self.assertEqual(artifact["explainability_version"], "p0.4-v1")
        self.assertEqual(artifact["formula_registry_version"], "p1.3-v1")
        self.assertEqual(artifact["importance_methods"], ["holdout_permutation_importance", "native_tree_importance"])
        self.assertEqual(artifact["permutation_repeats"], 20)
        validate_model_explainability(artifact)
    def setUp(self):
        self.names = [
            "validation_metrics.json", "forecast_output.json", "directives.json",
            "dashboard_summary.json", "pipeline_run_summary.json", "model_comparison.json",
            "chart_data.json", "model_card.json", "model_explainability.json",
        ]
        self.values = {name: json.loads((ROOT / "data" / name).read_text(encoding="utf-8")) for name in self.names}

    def test_all_artifacts_share_one_complete_provenance_identity(self):
        provenance = [artifact_provenance(self.values[name], name) for name in self.names]
        assert_same_provenance(*provenance, labels=self.names)
        for key in ("run_id", "manifest_sha256", "formula_registry_sha256", "deployment_profile_sha256", "evidence_registry_sha256", "model_card_id", "model_card_version"):
            self.assertEqual(len({item[key] for item in provenance}), 1)
        self.assertNotIn("run_id", self.values["model_explainability.json"].keys())

    def test_model_card_contains_exact_explainability_hash(self):
        raw = (ROOT / "data" / "selected_model_explainability.json").read_bytes()
        self.assertEqual(
            self.values["model_card.json"]["explainability_artifact_sha256"],
            hashlib.sha256(raw).hexdigest(),
        )

    def test_altered_bytes_stale_identity_and_malformed_artifact_fail(self):
        artifact = json.loads((ROOT / "data" / "selected_model_explainability.json").read_text())
        card = self.values["model_card.json"]
        self.assertNotEqual(card["selected_model_explainability_artifact_sha256"], "0" * 64)
        stale = copy.deepcopy(artifact)
        stale["provenance"]["run_id"] = "stale-run"
        with self.assertRaises((ExplainabilityError, ProvenanceError)):
            from explainability_engine import validate_selected_model_explainability
            validate_selected_model_explainability(stale, expected_provenance=artifact["provenance"])
        malformed = copy.deepcopy(artifact); del malformed["feature_ranking"]
        with self.assertRaises(ExplainabilityError):
            from explainability_engine import validate_selected_model_explainability
            validate_selected_model_explainability(malformed)

    def test_missing_artifact_yields_genuine_not_generated_state(self):
        summary = build_dashboard_summary(
            self.values["forecast_output.json"], self.values["validation_metrics.json"],
            self.values["directives.json"], self.values["model_card.json"], None,
        )
        status = summary["feature_importance"]
        self.assertEqual(status["status"], "not_generated")
        self.assertIn("No placeholder or prior-run values", status["message"])


if __name__ == "__main__":
    unittest.main()
