import json, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SelectedModelFrontendContractTests(unittest.TestCase):
    def test_compact_summary_reports_current_and_historical_identity(self):
        value = json.loads((ROOT / "data/dashboard_summary.json").read_text())
        comparison = value["candidate_model_comparison"]
        self.assertEqual(comparison["comparison_selected_model"], "random_forest")
        self.assertEqual(comparison["current_forecast_model"], "random_forest")
        self.assertEqual(comparison["adoption_status"], "adopted_p1.2b")
        self.assertEqual(value["feature_importance"]["model_id"], "random_forest")
        self.assertFalse(value["feature_importance"]["historical_gbr_evidence"]["active_model_evidence"])
        self.assertEqual(value["uncertainty"]["method_id"], "prequential_expanding_absolute_residual_quantile")
        self.assertFalse(value["uncertainty"]["is_prediction_interval"])
        self.assertNotIn("per_fold_predictions", comparison)
        self.assertNotIn("folds", value["rolling_validation"])


if __name__ == "__main__": unittest.main()
