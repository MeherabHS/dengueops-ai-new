from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DarkFrontendContractTest(unittest.TestCase):
    def test_p13_metrics_are_projected_from_committed_summary(self):
        summary = json.loads((ROOT / "data" / "dashboard_summary.json").read_text(encoding="utf-8"))
        uncertainty = summary["uncertainty"]
        for field in (
            "calibration_warmup_fold_count", "covered_fold_count", "evaluated_fold_count",
            "nominal_coverage", "observed_historical_coverage", "average_interval_width",
            "median_interval_width", "minimum_interval_width", "maximum_interval_width",
            "lower_miss_count", "upper_miss_count", "is_prediction_interval",
            "calibrated_on_synthetic_data", "uncertainty_status", "uncertainty_method",
            "uncertainty_method_version", "residual_source_artifact_path",
        ):
            self.assertIn(field, uncertainty)
        self.assertEqual(uncertainty["covered_fold_count"], 43)
        self.assertEqual(uncertainty["evaluated_fold_count"], 48)
        self.assertEqual(uncertainty["calibration_warmup_fold_count"], 20)

    def test_overview_uses_typed_committed_adapter_and_no_metric_literals(self):
        page = (ROOT / "app" / "dashboard" / "page.tsx").read_text(encoding="utf-8")
        adapter = (ROOT / "lib" / "dashboard-view-model.ts").read_text(encoding="utf-8")
        self.assertIn("bundledOverviewViewModel", page)
        self.assertNotIn("dashboardSummary", page)
        self.assertNotIn("forecastOutput", page)
        self.assertIn('from "@/lib/demo-data"', adapter)
        self.assertIn('refreshState: "committed"', adapter)
        for literal in ("53–187", "43 / 48", "146.9243"):
            self.assertNotIn(literal, page)

    def test_animated_graph_uses_committed_values_and_reduced_motion(self):
        chart = (ROOT / "components" / "overview" / "ForecastTrendChart.tsx").read_text(encoding="utf-8")
        for term in ("history", "forecast", "lower", "upper", "connector", "ErrorBar", "prefers-reduced-motion", "isAnimationActive"):
            self.assertIn(term, chart)
        self.assertIn("figcaption", chart)

    def test_preparedness_is_count_based_and_horizon_labelled(self):
        page = (ROOT / "app" / "dashboard" / "page.tsx").read_text(encoding="utf-8")
        card = (ROOT / "components" / "overview" / "PreparednessCountCard.tsx").read_text(encoding="utf-8")
        self.assertIn("NS1/RDT stock horizon ≤14 days", page)
        self.assertIn("IV-fluid stock horizon ≤14 days", page)
        self.assertIn("of {total} facilities", card)
        self.assertIn('role="progressbar"', card)
        self.assertIn("criticalReviewFacilities", page)

    def test_active_rf_and_historical_gbr_are_unambiguous(self):
        evidence = (ROOT / "components" / "evidence" / "EvidenceTabs.tsx").read_text(encoding="utf-8")
        self.assertIn("Active Random Forest rolling performance", evidence)
        self.assertIn("Historical P1.1 Gradient Boosting rolling-validation evidence — not active-model performance", evidence)
        self.assertIn("Not active-model evidence", evidence)

    def test_machine_statuses_are_centralized(self):
        labels = (ROOT / "lib" / "status-labels.ts").read_text(encoding="utf-8")
        for raw in (
            "comparison_complete_and_adopted", "adopted_p1.2b",
            "temporally_evaluated_synthetic_empirical_range", "benchmark_only",
            "synthetic_capability_demonstration", "random_forest", "gradient_boosting",
        ):
            self.assertIn(raw, labels)

    def test_dark_tokens_are_centralized(self):
        styles = (ROOT / "app" / "globals.css").read_text(encoding="utf-8")
        for token in ("--page-background", "--surface-elevated", "--surface-raised", "--accent", "--chart-range", "--focus"):
            self.assertIn(token, styles)


if __name__ == "__main__":
    unittest.main()
