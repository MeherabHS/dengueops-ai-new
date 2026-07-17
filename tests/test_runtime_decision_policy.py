import hashlib
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]


class DecisionPolicyTests(unittest.TestCase):
    def test_active_phase_two_policy_hash_scope_and_prohibitions(self):
        policy = json.loads((ROOT / "config/deployments/dhaka_south/decision_policy.json").read_text())
        schema = json.loads((ROOT / "config/runtime_decision_policy.schema.json").read_text())
        Draft202012Validator(schema).validate(policy)
        expected = policy.pop("policySha256")
        digest = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(digest, expected)
        self.assertEqual((policy["schemaVersion"], policy["policyVersion"]), ("2.0", "p2-v1"))
        self.assertEqual(policy["successfulFoldRequirement"]["source"], "committed_assessment_planned_fold_count")
        self.assertEqual(policy["selectedModelTrainingPolicy"]["scope"], "all_validated_labelled_rows")
        self.assertEqual(policy["decisionScope"], "one_run")
        self.assertFalse(policy["baselineApprovalAllowed"])
        self.assertFalse(policy["deploymentWideAdoptionAllowed"])

    def test_archived_phase_one_policy_bytes_and_canonical_identity_are_unchanged(self):
        path = ROOT / "config/deployments/dhaka_south/decision_policy_p1.4d-3-e-v1.json"
        raw = path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "b481ca775fd1c1927d87fa2e463bf93d199ffbe5e7977346b665a2363b64f875")
        policy = json.loads(raw)
        self.assertEqual((policy["policyId"], policy["policyVersion"], policy["policySha256"]),
                         ("RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION", "p1.4d-3-e-v1",
                          "8fece340b85951d3bee8b037c4ac79ae82636ee371a934e9371bcb4a633491a4"))
        Draft202012Validator(json.loads((ROOT / "config/runtime_decision_policy.schema.json").read_text())).validate(policy)

    def test_loader_routes_only_immutable_phase_one_and_phase_two_identities(self):
        source = (ROOT / "lib/runtime/decision-policy.ts").read_text()
        self.assertIn('filename = "decision_policy_p1.4d-3-e-v1.json"', source)
        self.assertIn('filename = "decision_policy.json"', source)
        self.assertIn("PHASE_ONE_ASSESSMENT_SHA", source)
        self.assertIn("PHASE_TWO_ASSESSMENT_SHA", source)
        self.assertIn("decision_policy_mismatch", source)
        self.assertNotIn("fallback", source.lower())


if __name__ == "__main__":
    unittest.main()
