import copy,hashlib,json,sys,unittest
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/"analytics"))
from runtime_forecast_outcome_policy import P1_SHA,P2_SHA,canonical_policy_sha256

class ForecastOutcomeSchemaTests(unittest.TestCase):
    def test_policy_archive_and_active_hashes(self):
        archived=json.loads((ROOT/"config/deployments/dhaka_south/forecast_outcome_policy_p1.4g-v1.json").read_text())
        active=json.loads((ROOT/"config/deployments/dhaka_south/forecast_outcome_policy.json").read_text())
        self.assertEqual((canonical_policy_sha256(archived),archived["policy_sha256"]),(P1_SHA,P1_SHA))
        self.assertEqual(hashlib.sha256((ROOT/"config/deployments/dhaka_south/forecast_outcome_policy_p1.4g-v1.json").read_bytes()).hexdigest(),"3c9c1ec14ecefcff0fc6310fd449e9846089593912b5a09885647fe3449660e6")
        self.assertEqual((canonical_policy_sha256(active),active["policy_sha256"]),(P2_SHA,P2_SHA))
        self.assertEqual(set(active["source_families"]),{"quick_forecast_p1","approved_forecast_p1","approved_forecast_p2"})

    def test_policy_schema_rejects_hybrid_and_extra_keys(self):
        schema=json.loads((ROOT/"config/runtime_forecast_outcome_policy.schema.json").read_text());validator=Draft202012Validator(schema)
        active=json.loads((ROOT/"config/deployments/dhaka_south/forecast_outcome_policy.json").read_text())
        self.assertFalse(list(validator.iter_errors(active)))
        for mutation in (lambda v:v.update(schema_version="1.0"),lambda v:v.update(extra=True),lambda v:v["source_families"].pop("approved_forecast_p2")):
            value=copy.deepcopy(active);mutation(value);self.assertTrue(list(validator.iter_errors(value)))

    def test_outcome_schema_has_disjoint_source_evidence(self):
        schema=json.loads((ROOT/"config/runtime_forecast_outcome.schema.json").read_text())
        phase2=schema["$defs"]["phase2"]
        self.assertEqual(set(phase2["properties"]["sourceFamily"]["enum"]),{"quick_forecast_p1","approved_forecast_p1","approved_forecast_p2"})
        self.assertIn("forecastCalibrationPath",schema["$defs"]["quickEvidence"]["required"])
        self.assertNotIn("forecastCalibrationPath",schema["$defs"]["approvedEvidence"]["properties"])
        self.assertIn("authorizationCommitSha256",schema["$defs"]["approvedEvidence"]["required"])

    def test_approved_evidence_accepts_dynamic_history_independent_of_folds(self):
        schema=json.loads((ROOT/"config/runtime_forecast_outcome.schema.json").read_text());validator=Draft202012Validator({"$schema":schema["$schema"],"$defs":schema["$defs"],"$ref":"#/$defs/approvedEvidence"})
        sha="0"*64;policy={"policyId":"x","policyVersion":"x","policySha256":sha};period={"start":"2021-W01","end":"2024-W01"}
        base={"forecastOutputPath":"artifacts/forecast_output.json","forecastOutputSha256":sha,"forecastUncertaintyPath":"artifacts/forecast_uncertainty.json","forecastUncertaintySha256":sha,"modelCardPath":"artifacts/model_card.json","modelCardSha256":sha,"sourcePolicy":policy,"assessmentId":"00000000-0000-4000-8000-000000000000","assessmentCommitSha256":sha,"assessmentPolicy":policy,"decisionId":"00000000-0000-4000-8000-000000000001","decisionCommitSha256":sha,"decisionPolicy":policy,"authorizationId":"00000000-0000-4000-8000-000000000002","authorizationCommitSha256":sha,"technicalWinnerModelId":"random_forest","technicalWinnerParameterSha256":sha,"trainingPeriod":period,"failedFolds":0,"selectedEvaluationPeriod":period,"foldPlanSha256":sha,"featureMatrixSha256":sha}
        for rows,folds in ((157,52),(158,53),(173,68),(183,68)):
            value={**base,"trainingRowCount":rows,"plannedFoldCount":folds,"successfulFolds":folds};self.assertFalse(list(validator.iter_errors(value)),(rows,folds))

if __name__=="__main__":unittest.main()
