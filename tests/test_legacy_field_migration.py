from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from forecast_model import GROWTH_CATEGORY_LABELS, _scenario, classify_risk  # noqa: E402


LEGACY_KEYS = {"risk_level", "risk_score", "recommendations"}
ACTIVE_BUNDLE = (
    "forecast_output.json",
    "directives.json",
    "dashboard_summary.json",
    "chart_data.json",
    "pipeline_run_summary.json",
)


def walk(value):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class LegacyFieldMigrationTest(unittest.TestCase):
    def test_growth_score_and_category_boundaries_are_unchanged(self):
        expected = {
            0.89: ("Low", 28),
            0.90: ("Low", 29),
            1.10: ("Moderate", 35),
            1.19: ("Moderate", 41),
            1.20: ("Moderate", 41),
            1.49: ("Moderate", 59),
            1.50: ("High", 60),
            2.00: ("Critical", 85),
            2.20: ("Critical", 87),
        }
        for growth, result in expected.items():
            with self.subTest(growth=growth):
                self.assertEqual(classify_risk(growth), result)

    def test_scenario_is_canonical_only(self):
        scenario = _scenario("Point forecast", 150, 100.0)
        old_category, old_score = classify_risk(1.5)
        self.assertEqual(scenario["experimental_growth_score"], old_score)
        self.assertEqual(scenario["forecast_growth_category"], GROWTH_CATEGORY_LABELS[old_category])
        self.assertTrue(LEGACY_KEYS.isdisjoint(scenario))

    def test_governed_benchmark_numeric_and_suggestion_outputs_are_unchanged(self):
        forecast = json.loads((ROOT / "data" / "forecast_output.json").read_text(encoding="utf-8"))
        self.assertEqual((forecast["forecast_cases"], forecast["growth_factor"]), (120, 1.72))
        self.assertEqual((forecast["experimental_growth_score"], forecast["forecast_growth_category"]), (71, "High forecast growth"))
        self.assertEqual(
            [(item["forecast_cases"], item["experimental_growth_score"], item["forecast_growth_category"])
             for item in forecast["preparedness_scenarios"].values()],
            [(87, 44, "Moderate forecast growth"), (120, 71, "High forecast growth"), (153, 87, "Very high forecast growth")],
        )
        directives = json.loads((ROOT / "data" / "directives.json").read_text(encoding="utf-8"))
        self.assertEqual([item["priority_score"] for item in directives["directives"]], [100] * 10)
        labels = [item["label"] for item in directives["directives"][0]["planning_suggestions"]]
        self.assertEqual(labels, [
            "Prioritize vector-control response in this zone.",
            "Prepare triage desk and surge OPD workflow.",
            "Prepare contingency plan under worst-case forecast.",
        ])

    def test_active_generated_bundle_is_canonical_only(self):
        for name in ACTIVE_BUNDLE:
            value = json.loads((ROOT / "data" / name).read_text(encoding="utf-8"))
            for node in walk(value):
                if isinstance(node, dict):
                    self.assertTrue(LEGACY_KEYS.isdisjoint(node), f"{name} contains a legacy key")

        forecast = json.loads((ROOT / "data" / "forecast_output.json").read_text(encoding="utf-8"))
        self.assertIn("forecast_growth_category", forecast)
        self.assertIn("experimental_growth_score", forecast)
        for scenario in forecast["preparedness_scenarios"].values():
            self.assertIn("forecast_growth_category", scenario)
            self.assertIn("experimental_growth_score", scenario)
        for scenario in forecast["uncertainty_scenarios"].values():
            self.assertIn("forecast_growth_category", scenario)
            self.assertIn("experimental_growth_score", scenario)

        directives = json.loads((ROOT / "data" / "directives.json").read_text(encoding="utf-8"))
        for directive in directives["directives"]:
            self.assertIn("planning_suggestions", directive)
            for suggestion in directive["planning_suggestions"]:
                self.assertTrue(suggestion["label"])
                self.assertIn("formula_ids", suggestion)
                self.assertIn("approval_status", suggestion)
                self.assertIn("disclaimer", suggestion)

    def test_producers_and_operational_consumers_do_not_read_legacy_compatibility(self):
        for relative in (
            "analytics/forecast_model.py",
            "analytics/operational_engine.py",
            "analytics/dashboard_exporter.py",
            "analytics/run_pipeline.py",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("legacy_compatibility", source, relative)


if __name__ == "__main__":
    unittest.main()
