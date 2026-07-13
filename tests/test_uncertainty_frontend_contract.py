import json, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UncertaintyFrontendContractTests(unittest.TestCase):
    def test_compact_summary_separates_range_and_planning(self):
        value = json.loads((ROOT / "data/dashboard_summary.json").read_text())
        uncertainty = value["uncertainty"]
        self.assertEqual(uncertainty["method_id"], "prequential_expanding_absolute_residual_quantile")
        self.assertFalse(uncertainty["is_prediction_interval"])
        self.assertEqual(value["preparedness_scenarios"]["status"], "legacy_rf_rmse_planning_sensitivity_separate_from_forecast_uncertainty")
        self.assertNotIn("historical_evaluation", uncertainty)

    def test_safe_current_state_wording_and_no_full_artifact_import(self):
        files = [ROOT / "app/dashboard/page.tsx", ROOT / "components/dashboard/UncertaintySummary.tsx",
                 ROOT / "components/validation/UncertaintyLinkageSection.tsx"]
        text = "\n".join(path.read_text(encoding="utf-8").lower() for path in files)
        self.assertIn("empirical forecast range", text)
        self.assertIn("planning sensitivity", text)
        for forbidden in ("90% chance", "guaranteed range", "statistically certain"):
            self.assertNotIn(forbidden, text)
        self.assertNotIn('forecast_uncertainty.json"', text)

    def test_redesigned_routes_keep_range_and_planning_separate(self):
        nav = (ROOT / "lib/constants.ts").read_text(encoding="utf-8")
        overview = "\n".join((ROOT / path).read_text(encoding="utf-8").lower() for path in (
            "app/dashboard/page.tsx", "components/dashboard/UncertaintySummary.tsx"
        ))
        preparedness = (ROOT / "app/preparedness/page.tsx").read_text(encoding="utf-8").lower()
        forecast = (ROOT / "components/forecast/ForecastRunWorkflow.tsx").read_text(encoding="utf-8").lower()
        for route in ('"/dashboard"', '"/forecast"', '"/preparedness"', '"/validation"'):
            self.assertIn(route, nav)
        self.assertIn("empirical forecast range", overview)
        self.assertNotIn("preparedness_scenarios", overview)
        self.assertIn("planning sensitivity scenarios", preparedness)
        self.assertIn("start quick forecast", forecast)
        self.assertIn("start dataset assessment", forecast)
        self.assertIn('job.status === "completed"', forecast)
        self.assertIn("validateruntimedatasets", forecast)
        self.assertNotIn("ready to forecast", forecast)


if __name__ == "__main__": unittest.main()
