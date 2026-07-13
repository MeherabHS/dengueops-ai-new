from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from formula_registry import get_parameter, registry_sha256  # noqa: E402
from operational_engine import EXPOSURE_WEIGHTS  # noqa: E402


class FormulaConsistencyTest(unittest.TestCase):
    def test_python_parameters_match_registry(self):
        self.assertEqual(EXPOSURE_WEIGHTS["population_share"], get_parameter("OPS.EXPOSURE.COMPOSITION", "population_weight"))
        self.assertEqual(sum(EXPOSURE_WEIGHTS.values()), 1.0)

    def test_no_active_placeholder_import_and_spatial_stub_is_deprecated(self):
        demo = (ROOT / "lib" / "demo-data.ts").read_text(encoding="utf-8")
        self.assertNotIn("data/placeholder", demo)
        spatial = (ROOT / "analytics" / "spatial_exposure_engine.py").read_text(encoding="utf-8")
        self.assertIn("deprecated and non-executable", spatial)
        self.assertNotIn("W_DENSITY", spatial)

    def test_generated_artifacts_share_formula_registry_hash(self):
        artifacts = []
        for name in ("validation_metrics.json", "forecast_uncertainty.json", "forecast_output.json", "directives.json", "dashboard_summary.json", "pipeline_run_summary.json"):
            value = json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
            artifacts.append(value)
        self.assertEqual({a["formula_registry_sha256"] for a in artifacts}, {registry_sha256()})
        self.assertEqual({a["formula_registry_version"] for a in artifacts}, {"p1.3-v1"})
        self.assertEqual({a["deployment_gate"] for a in artifacts}, {"benchmark_only"})

    def test_frontend_consumes_generated_threshold_policy(self):
        for relative in ("lib/risk-utils.ts", "lib/surgeScenarios.ts", "components/charts/SupplyDepletionChart.tsx"):
            content = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("formula_policy", content)
        supply = (ROOT / "components/charts/SupplyDepletionChart.tsx").read_text(encoding="utf-8")
        self.assertNotIn("SDH_WARNING_THRESHOLD", supply)

    def test_documentation_uses_positive_deficit_and_provisional_labels(self):
        project = (ROOT / "docs" / "PROJECT_SUMMARY.md").read_text(encoding="utf-8")
        self.assertIn("Positive Bed Deficit = max(0, Projected Load − Dengue Capacity)", project)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Experimental Growth Score", readme)
        self.assertIn("not institution-approved", readme)


if __name__ == "__main__":
    unittest.main()
