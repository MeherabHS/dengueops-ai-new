from __future__ import annotations
import json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"analytics"))
from model_candidates import select_comparison_winner

class CandidateComparisonTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.artifact=json.loads((ROOT/"data/candidate_model_comparison.json").read_text())
    def test_all_candidates_use_identical_complete_folds(self):
        artifact=self.artifact; rolling=json.loads((ROOT/"data/rolling_validation.json").read_text()); ids=[f["fold_id"] for f in rolling["folds"]]
        self.assertEqual(len(artifact["candidates"]),7)
        for records in artifact["per_fold_predictions"].values(): self.assertEqual([r["fold_id"] for r in records],ids)
        self.assertTrue(all(m["successful_folds"]==68 and m["failed_folds"]==0 for m in artifact["aggregate_metrics"].values()))
    def test_reused_predictions_and_seasonal_sources(self):
        rolling=json.loads((ROOT/"data/rolling_validation.json").read_text()); a=self.artifact
        for candidate,source in (("gradient_boosting","gradient_boosting"),("previous_week_naive","naive"),("moving_average_4w","moving_average")):
            self.assertEqual([r["raw_prediction"] for r in a["per_fold_predictions"][candidate]],[f["predictions"][source]["raw_prediction"] for f in rolling["folds"]])
        seasonal=a["per_fold_predictions"]["seasonal_naive_52w"]; self.assertEqual(seasonal[0]["seasonal_source_period"],"2022-W09"); self.assertEqual(seasonal[-1]["seasonal_source_period"],"2023-W24")
    def test_selection_rule_is_generic_and_non_adopting(self):
        candidates=[{"model_id":"z","selection_complexity_rank":2},{"model_id":"a","selection_complexity_rank":1}]
        base={"successful_folds":68,"failed_folds":0,"mae":1.0,"rmse":2.0,"wape":3.0,"median_absolute_error":1.0,"maximum_absolute_error":4.0}
        winner,_,_=select_comparison_winner({"z":dict(base),"a":dict(base)},candidates); self.assertEqual(winner,"a")
        failed=dict(base,successful_folds=67,failed_folds=1,mae=0.0); winner,_,_=select_comparison_winner({"z":base,"a":failed},candidates); self.assertEqual(winner,"z")
        self.assertEqual(self.artifact["adoption_status"],"not_adopted_p1.2a"); self.assertEqual(self.artifact["current_forecast_model"],"gradient_boosting")
if __name__=="__main__": unittest.main()
