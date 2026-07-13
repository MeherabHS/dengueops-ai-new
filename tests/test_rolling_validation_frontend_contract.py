from __future__ import annotations
import json, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
class RollingValidationFrontendContractTest(unittest.TestCase):
    def test_generated_summary_is_primary_source(self):
        summary = json.loads((ROOT / "data" / "dashboard_summary.json").read_text())
        rolling = summary["rolling_validation"]
        self.assertFalse(rolling["primary_validation"]); self.assertFalse(rolling["active_model_evidence"]); self.assertEqual(rolling["fold_count"], 68)
        self.assertEqual(rolling["legacy_holdout"]["validation_role"], "legacy_single_holdout")
        self.assertEqual(rolling["permutation_stability_status"], "not_evaluated_single_row_folds")
    def test_frontend_has_no_hardcoded_claims(self):
        sources = "\n".join((ROOT / p).read_text() for p in ["lib/demo-data.ts", "components/validation/ValidationHero.tsx", "components/validation/ValidationDesignSection.tsx", "components/validation/ModelSummaryCards.tsx", "components/validation/ModelComparisonTable.tsx"])
        self.assertIn("dashboardSummary.rolling_validation", sources)
        self.assertNotIn("29 engineered features", sources)
        self.assertNotIn("GradientBoostingRegressor was selected because", sources)
        self.assertIn("label_availability_policy", sources)
        self.assertIn("not real-world epidemiological validity", sources)
if __name__ == "__main__": unittest.main()
