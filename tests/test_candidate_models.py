from __future__ import annotations
import copy, json, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"analytics"))
from model_candidates import _estimator, _sha, load_candidate_registry
from feature_engineering import FEATURE_COLUMNS

class CandidateModelsTest(unittest.TestCase):
    def test_registry_schema_hashes_and_exact_set(self):
        registry=load_candidate_registry(); candidates=registry["candidates"]
        self.assertEqual(len(candidates),7); self.assertEqual(len({c["model_id"] for c in candidates}),7)
        self.assertEqual(registry["feature_order_sha256"],_sha(list(FEATURE_COLUMNS)))
        for candidate in candidates: self.assertEqual(candidate["parameters_sha256"],_sha(candidate["parameters"]))
        self.assertNotIn("parameter_grid",json.dumps(registry)); self.assertTrue(all(c["enabled"] for c in candidates))
    def test_fold_local_estimators_are_new_instances(self):
        registry=load_candidate_registry()
        for model_id in ("ridge_regression","poisson_regression","random_forest"):
            params=next(c["parameters"] for c in registry["candidates"] if c["model_id"]==model_id)
            self.assertIsNot(_estimator(model_id,params),_estimator(model_id,params))
    def test_declared_preprocessing_and_libraries(self):
        candidates={c["model_id"]:c for c in load_candidate_registry()["candidates"]}
        self.assertEqual(candidates["ridge_regression"]["preprocessing"]["fit_scope"],"fold_training_rows_only")
        self.assertEqual(candidates["poisson_regression"]["preprocessing"]["fit_scope"],"fold_training_rows_only")
        self.assertEqual(candidates["random_forest"]["parameters"]["n_jobs"],1)
        self.assertEqual(candidates["gradient_boosting"]["parameters_sha256"],"4741d1f17b3bf98988b886dcb6157a9382b569e3264e1004d2f3eb474bd34963")
if __name__=="__main__": unittest.main()
