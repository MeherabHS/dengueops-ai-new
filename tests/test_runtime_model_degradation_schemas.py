import copy,json,unittest
from pathlib import Path
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[1]
class ModelDegradationSchemaTests(unittest.TestCase):
    def test_policy_schema_rejects_extra_threshold_window_and_actions(self):
        policy=json.loads((ROOT/"config/deployments/dhaka_south/model_degradation_evidence_policy.json").read_text());schema=json.loads((ROOT/"config/runtime_model_degradation_evidence_policy.schema.json").read_text());validator=Draft202012Validator(schema);self.assertFalse(list(validator.iter_errors(policy)))
        mutations=(lambda v:v.update(extra=True),lambda v:v.update(degradationThresholds={"mae":1}),lambda v:v["monitoring_window"].update(windowOutcomeCount=4),lambda v:v.update(materialWorseningClassificationAllowed=True),lambda v:v.update(lifecycleRecommendationAllowed=True))
        for mutate in mutations:value=copy.deepcopy(policy);mutate(value);self.assertTrue(list(validator.iter_errors(value)))
    def test_job_schema_has_strict_degradation_branch(self):
        schema=json.loads((ROOT/"config/runtime_job.schema.json").read_text())
        for name,version in (("degradationEvidence","p2-v1"),("degradationEvidenceP2","p2-v2")):
            branch=schema["$defs"][name];self.assertFalse(branch["additionalProperties"]);self.assertEqual(branch["properties"]["jobKind"]["const"],"degradation_evidence");self.assertEqual(branch["properties"]["policyVersion"]["const"],version);self.assertNotIn("selectedModelId",branch["properties"]);self.assertNotIn("windowOutcomeCount",branch["properties"])
    def test_schema_version_branches_are_strict_and_disjoint(self):
        names=("runtime_model_degradation_evidence.schema.json","runtime_model_degradation_summary.schema.json","runtime_model_degradation_commit.schema.json","runtime_model_degradation_latest.schema.json")
        for name in names:
            schema=json.loads((ROOT/"config"/name).read_text());self.assertEqual(set(schema["$defs"]) >= {"p1","p2"},True);self.assertFalse(schema["$defs"]["p1"]["additionalProperties"]);self.assertFalse(schema["$defs"]["p2"]["additionalProperties"])
            p1=copy.deepcopy(schema["$defs"]["p1"]);p2=schema["$defs"]["p2"]
            self.assertEqual(p1["properties"]["schemaVersion"]["const"],"1.0");self.assertEqual(p2["properties"]["schemaVersion"]["const"],"2.0")
if __name__=="__main__":unittest.main()
