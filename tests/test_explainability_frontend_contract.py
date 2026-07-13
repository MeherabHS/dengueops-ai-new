from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExplainabilityFrontendContractTest(unittest.TestCase):
    def test_generated_diagnostics_are_consumed_without_placeholder_or_hardcoded_array(self):
        demo = (ROOT / "lib" / "demo-data.ts").read_text(encoding="utf-8")
        self.assertIn("dashboardSummaryTyped.feature_importance", demo)
        self.assertNotIn("dashboardSummaryAny", demo)
        self.assertNotIn("data/placeholder", demo)
        self.assertNotIn("featureImportance: FeatureImportanceItem[] = []", demo)

    def test_required_warnings_and_unavailable_state_are_visible(self):
        view = (ROOT / "components" / "dashboard" / "TechnicalValidationView.tsx").read_text(encoding="utf-8")
        exporter = (ROOT / "analytics" / "dashboard_exporter.py").read_text(encoding="utf-8")
        engine = (ROOT / "analytics" / "explainability_engine.py").read_text(encoding="utf-8")
        combined = view + exporter + engine
        for text in (
            "Selected Random Forest Feature Diagnostics",
            "does not establish causality",
            "selected Random Forest validation-model instance",
            "not evaluated across temporal folds",
            "synthetic benchmark data and may not transfer to real surveillance data",
            "No placeholder or prior-run values are displayed",
        ):
            self.assertIn(text, combined)

    def test_chart_preserves_negative_values_and_has_dynamic_domain(self):
        chart = (ROOT / "components" / "charts" / "FeatureImportanceChart.tsx").read_text(encoding="utf-8")
        self.assertIn("Math.min(0, ...bounds)", chart)
        self.assertIn("Math.max(0, ...bounds)", chart)
        self.assertIn("<ReferenceLine x={0}", chart)
        self.assertIn("permutation_standard_deviation", chart)
        self.assertNotIn("domain={[0, 0.4]}", chart)
        self.assertNotIn("Math.max(0, item.permutation_mean", chart)

    def test_prohibited_causal_phrases_are_absent(self):
        paths = [
            ROOT / "analytics" / "explainability_engine.py",
            ROOT / "components" / "dashboard" / "TechnicalValidationView.tsx",
            ROOT / "components" / "charts" / "FeatureImportanceChart.tsx",
        ]
        content = " ".join(path.read_text(encoding="utf-8").lower() for path in paths)
        for phrase in ("strongest autoregressive signal", "most important epidemiological driver", "rainfall causes dengue", "strongest disease determinant"):
            self.assertNotIn(phrase, content)


if __name__ == "__main__":
    unittest.main()
