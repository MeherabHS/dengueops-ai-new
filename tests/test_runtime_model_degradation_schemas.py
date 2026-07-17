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
        schema=json.loads((ROOT/"config/runtime_job.schema.json").read_text());branch=schema["$defs"]["degradationEvidence"];self.assertFalse(branch["additionalProperties"]);self.assertEqual(branch["properties"]["jobKind"]["const"],"degradation_evidence");self.assertNotIn("selectedModelId",branch["properties"]);self.assertNotIn("windowOutcomeCount",branch["properties"])
if __name__=="__main__":unittest.main()
