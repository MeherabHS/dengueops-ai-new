import copy,hashlib,json,sys,unittest
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/"analytics"))
from runtime_forecast_outcome_policy import P1_SHA,P2_SHA,P21_SHA,canonical_policy_sha256

class ForecastOutcomeSchemaTests(unittest.TestCase):
    def test_policy_archive_and_active_hashes(self):
        archived=json.loads((ROOT/"config/deployments/dhaka_south/forecast_outcome_policy_p1.4g-v1.json").read_text())
        active=json.loads((ROOT/"config/deployments/dhaka_south/forecast_outcome_policy.json").read_text())
        self.assertEqual((canonical_policy_sha256(archived),archived["policy_sha256"]),(P1_SHA,P1_SHA))
        self.assertEqual(hashlib.sha256((ROOT/"config/deployments/dhaka_south/forecast_outcome_policy_p1.4g-v1.json").read_bytes()).hexdigest(),"3c9c1ec14ecefcff0fc6310fd449e9846089593912b5a09885647fe3449660e6")
        archived_p2=ROOT/"config/deployments/dhaka_south/forecast_outcome_policy_p2-v1.json"
        self.assertEqual(hashlib.sha256(archived_p2.read_bytes()).hexdigest(),"5ea1b4c280363566ece446a50657339b55ed865b4550774d677b4291c34c84c0")
        self.assertEqual((canonical_policy_sha256(active),active["policy_sha256"]),(P21_SHA,P21_SHA))
        self.assertEqual(set(active["source_families"]),{"quick_forecast_p1","quick_forecast_p2","approved_forecast_p1","approved_forecast_p2"})

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
        self.assertNotIn("quick_forecast_p2",phase2["properties"]["sourceFamily"]["enum"])
        self.assertIn("extra_trees",phase2["properties"]["modelId"]["enum"])
        self.assertEqual(set(phase2["properties"]["candidateRegistrySha256"]["enum"]),{
            "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4",
            "74cb3635c5e211874ee5ad23196fc95bfdfbdb5c6438cc3d060f0b9ff49acfa0"})
        self.assertIn("forecastCalibrationPath",schema["$defs"]["quickEvidence"]["required"])
        self.assertNotIn("forecastCalibrationPath",schema["$defs"]["approvedEvidence"]["properties"])
        self.assertIn("authorizationCommitSha256",schema["$defs"]["approvedEvidence"]["required"])
        phase21=schema["$defs"]["phase21"]
        self.assertIn("quick_forecast_p2",phase21["properties"]["sourceFamily"]["enum"])
        self.assertIn("runRecordSha256",schema["$defs"]["quickP2Evidence"]["required"])
        self.assertIn("assignmentProvenance",schema["$defs"]["quickP2Evidence"]["required"])

    def test_assignment_2_0_schemas_are_closed_and_keep_historical_branches(self):
        record=json.loads((ROOT/"config/runtime_model_assignment.schema.json").read_text())
        commit=json.loads((ROOT/"config/runtime_model_assignment_commit.schema.json").read_text())
        record_versions=[branch["properties"]["schemaVersion"]["const"] for branch in record["oneOf"]]
        commit_versions=[branch["properties"]["schemaVersion"]["const"] for branch in commit["oneOf"]]
        self.assertEqual(record_versions.count("1.0"),3);self.assertEqual(record_versions.count("2.0"),1)
        self.assertEqual(commit_versions.count("1.0"),3);self.assertEqual(commit_versions.count("2.0"),1)
        current_record=next(branch for branch in record["oneOf"] if branch["properties"]["schemaVersion"]["const"]=="2.0")
        current_commit=next(branch for branch in commit["oneOf"] if branch["properties"]["schemaVersion"]["const"]=="2.0")
        self.assertFalse(current_record["additionalProperties"]);self.assertFalse(current_commit["additionalProperties"])
        self.assertEqual(set(current_commit["required"]),{"schemaVersion","assignmentId","assignmentRecordSha256","committedAt"})
        canonical=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        self.assertEqual([canonical(branch) for branch in record["oneOf"][:3]],["4f562090a22b05cb917e30e7f3cde507b35f67042be93ee9e34ecd33fc232b14","b8d971809f7de31068e8c6eab559b128e4fd8eb2bae70962a7ad3915576d2ac9","6e553ed9fb7d5d57b367b301e0229729b722f9f83c6db23d55466a5fcd783a3a"])
        self.assertEqual([canonical(branch) for branch in commit["oneOf"][:3]],["84cb367b95fb4e28a5f04c883888e748cb8b4775f8e51804ba791dbca6f73011","06898a19249e9900035dbd3485378f3d22e608464ac9e6261e96faae8103c80f","a533ad02abd17b4684aba0794559fde9b4c4313517acf14393f5cbee8cd90422"])

    def test_approved_evidence_accepts_dynamic_history_independent_of_folds(self):
        schema=json.loads((ROOT/"config/runtime_forecast_outcome.schema.json").read_text());validator=Draft202012Validator({"$schema":schema["$schema"],"$defs":schema["$defs"],"$ref":"#/$defs/approvedEvidence"})
        sha="0"*64;policy={"policyId":"x","policyVersion":"x","policySha256":sha};period={"start":"2021-W01","end":"2024-W01"}
        base={"forecastOutputPath":"artifacts/forecast_output.json","forecastOutputSha256":sha,"forecastUncertaintyPath":"artifacts/forecast_uncertainty.json","forecastUncertaintySha256":sha,"modelCardPath":"artifacts/model_card.json","modelCardSha256":sha,"sourcePolicy":policy,"assessmentId":"00000000-0000-4000-8000-000000000000","assessmentCommitSha256":sha,"assessmentPolicy":policy,"decisionId":"00000000-0000-4000-8000-000000000001","decisionCommitSha256":sha,"decisionPolicy":policy,"authorizationId":"00000000-0000-4000-8000-000000000002","authorizationCommitSha256":sha,"technicalWinnerModelId":"random_forest","technicalWinnerParameterSha256":sha,"trainingPeriod":period,"failedFolds":0,"selectedEvaluationPeriod":period,"foldPlanSha256":sha,"featureMatrixSha256":sha}
        for rows,folds in ((157,52),(158,53),(173,68),(183,68)):
            value={**base,"trainingRowCount":rows,"plannedFoldCount":folds,"successfulFolds":folds};self.assertFalse(list(validator.iter_errors(value)),(rows,folds))

if __name__=="__main__":unittest.main()
