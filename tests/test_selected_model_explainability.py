import json, math, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
from explainability_engine import validate_selected_model_explainability
from feature_engineering import FEATURE_COLUMNS
from provenance import provenance_from_feature_frame
from validation_backtest import load_feature_matrix


class SelectedModelExplainabilityTests(unittest.TestCase):
    def test_selected_diagnostic_contract_and_legacy_separation(self):
        artifact = json.loads((ROOT / "data/selected_model_explainability.json").read_text())
        frame = load_feature_matrix(); split = int(len(frame) * .8)
        validate_selected_model_explainability(
            artifact, expected_provenance=provenance_from_feature_frame(frame),
            expected_feature_names=FEATURE_COLUMNS, expected_validation_df=frame.iloc[split:].copy(),
        )
        self.assertEqual(artifact["selected_model_id"], "random_forest")
        self.assertEqual((artifact["training_rows"], artifact["validation_rows"]), (138, 35))
        self.assertEqual(len(artifact["native_importance"]), 18)
        self.assertTrue(math.isclose(sum(artifact["native_importance"]), 1.0))
        self.assertEqual(artifact["permutation_settings"], {"scoring":"neg_mean_absolute_error","n_repeats":20,"random_state":42,"n_jobs":1,"max_samples":1.0})
        self.assertTrue(any(value < 0 for value in artifact["permutation_importance"]))
        self.assertEqual(artifact["rolling_importance_stability_status"], "not_evaluated_across_temporal_folds")
        legacy = json.loads((ROOT / "data/model_explainability.json").read_text())
        self.assertEqual(legacy["evidence_status"], "historical")
        self.assertFalse(legacy["active_model_evidence"])


if __name__ == "__main__": unittest.main()
