from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class CandidateFrontendContractTest(unittest.TestCase):
    def test_generated_summary_contains_governed_adoption(self):
        value=json.loads((ROOT/"data/dashboard_summary.json").read_text())["candidate_model_comparison"]
        self.assertEqual(value["model_selection_status"],"comparison_complete_and_adopted"); self.assertEqual(value["current_forecast_model"],"random_forest"); self.assertEqual(value["adoption_status"],"adopted_p1.2b")
        self.assertEqual(value["active_model_rolling_metrics"]["successful_folds"],68); self.assertIn("not a proven real-world dengue model",value["warning"])
    def test_frontend_is_artifact_driven_and_supports_not_run(self):
        source="\n".join((ROOT/p).read_text() for p in ["lib/demo-data.ts","components/validation/ModelComparisonTable.tsx","components/validation/ModelSummaryCards.tsx","components/validation/ValidationLimitations.tsx"])
        self.assertIn("candidateModelComparison",source); self.assertIn("not_run_current_pipeline",source); self.assertIn("failed_folds",source)
        self.assertNotIn("random_forest has the lowest",source); self.assertNotIn("universally superior",source)
if __name__=="__main__": unittest.main()
