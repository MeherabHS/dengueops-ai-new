import copy, json, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SelectedModelUncertaintyBindingTests(unittest.TestCase):
    def setUp(self):
        self.forecast = json.loads((ROOT / "data/forecast_output.json").read_text())

    def test_random_forest_temporal_binding_is_explicit(self):
        binding = self.forecast["forecast_uncertainty"]
        self.assertEqual(binding["active_model_id"], "random_forest")
        self.assertEqual(binding["method_id"], "prequential_expanding_absolute_residual_quantile")
        self.assertFalse(binding["is_prediction_interval"])
        self.assertTrue(binding["calibrated_on_synthetic_data"])

    def test_legacy_rmse_is_planning_only(self):
        method = self.forecast["preparedness_scenario_method"]
        self.assertEqual(method["type"], "legacy_rf_rmse_planning_sensitivity")
        self.assertFalse(method["calibrated"]); self.assertFalse(method["is_prediction_interval"])
        self.assertEqual(method["status"], "operational_planning_compatibility_only_not_forecast_interval")


if __name__ == "__main__": unittest.main()
