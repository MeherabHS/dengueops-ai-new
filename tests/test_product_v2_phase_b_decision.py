from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from model_factory import LEARNED_MODEL_IDS, load_and_validate_candidate_registry


def canonical(value: dict) -> str:
    content = dict(value)
    content.pop("policySha256", None)
    return hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class PhaseBDecisionPolicyTests(unittest.TestCase):
    def test_active_decision_policy_is_closed_p2_v2(self):
        policy = json.loads(
            (ROOT / "config/deployments/dhaka_south/decision_policy.json").read_text()
        )
        schema = json.loads((ROOT / "config/runtime_decision_policy.schema.json").read_text())
        errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy))
        self.assertEqual(errors, [])
        self.assertEqual(policy["policyVersion"], "p2-v2")
        self.assertEqual(policy["allowedAssessmentPolicyVersion"], "p2-v2")
        self.assertEqual(policy["allowedDecisions"], ["approve_technical_winner", "approve_eligible_non_winner"])
        self.assertEqual(policy["allowedCandidateStatuses"], ["technical_winner", "eligible_non_winner"])
        self.assertFalse(policy["deploymentWideAdoptionAllowed"])
        self.assertEqual(policy["policySha256"], canonical(policy))

    def test_decision_policy_binds_exact_v2_registry_and_learned_population(self):
        policy = json.loads(
            (ROOT / "config/deployments/dhaka_south/decision_policy.json").read_text()
        )
        registry, digest = load_and_validate_candidate_registry()
        self.assertEqual(policy["candidateRegistrySha256"], digest)
        self.assertEqual(set(policy["allowedCandidateIds"]), LEARNED_MODEL_IDS)
        self.assertFalse(any(candidate["candidate_class"] != "learned_model" for candidate in registry["candidates"] if candidate["model_id"] in policy["allowedCandidateIds"]))

    def test_archived_p2_v1_decision_policy_is_unchanged(self):
        archive = ROOT / "config/deployments/dhaka_south/decision_policy_p2-v1.json"
        self.assertEqual(
            hashlib.sha256(archive.read_bytes()).hexdigest(),
            "6ebde8d161c67ad1a4b31d79363d06093266ff48813c3771dfa3dc7da11723f1",
        )
        self.assertEqual(json.loads(archive.read_text())["policyVersion"], "p2-v1")


if __name__ == "__main__":
    unittest.main()
