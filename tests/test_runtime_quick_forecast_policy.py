import copy
import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
SPEC = importlib.util.spec_from_file_location("runtime_policy", ROOT / "analytics" / "runtime_policy.py")
runtime_policy = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(runtime_policy)


class RuntimeQuickForecastPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy, cls.policy_sha = runtime_policy.load_and_validate_quick_forecast_policy("dhaka_south")
        cls.registry_sha = hashlib.sha256((ROOT / "config" / "candidate_models.json").read_bytes()).hexdigest()

    def context(self):
        return {
            "validation_passed": True,
            "deployment_id": "dhaka_south",
            "deployment_gate": "benchmark_only",
            "case_geography": {"geography_level": "city", "geography_id": "BGD-DHAKA-SOUTH", "geography_name": "Dhaka South"},
            "climate_geography": {"geography_level": "city", "geography_id": "BGD-DHAKA-SOUTH", "geography_name": "Dhaka South"},
            "canonical_contract_version": "p1.4b-canonical-upload-v1",
            "feature_order_sha256": "aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85",
            "constructible_feature_count": 18,
            "target": "target_cases_next_2w",
            "horizon_weeks": 2,
            "approved_model_id": "random_forest",
            "approved_model_family": "RandomForestRegressor",
            "approved_model_parameters_sha256": "ac37d2d2947de2f6004d39ecdfa3290c5d65901b796f1eb1fd248ad658e1b1e0",
            "candidate_registry_sha256": self.registry_sha,
            "source_metadata": {
                "cases": {"source_type": "synthetic_benchmark", "aggregation_method": "weekly_epi_week_case_count", "contains_approximated_values": False},
                "climate": {"source_type": "synthetic_benchmark", "aggregation_method": "simulated_weekly_benchmark", "contains_approximated_values": False},
            },
            "overlap_weeks": 111,
            "labelled_rows": 104,
            "chronological_order_valid": True,
            "duplicate_periods_absent": True,
            "contiguous_history": True,
            "case_climate_aligned": True,
            "valid_inference_row": True,
        }

    def assert_blocked(self, mutation, code):
        context = self.context()
        mutation(context)
        result = runtime_policy.evaluate_quick_forecast_policy(self.policy, context)
        self.assertFalse(result["eligible"])
        self.assertIn(code, result["reasonCodes"])
        self.assertEqual(result["uncertaintyStatus"], "unavailable_for_uploaded_dataset")

    def test_policy_schema_hash_and_repository_identities(self):
        schema = json.loads((ROOT / "config" / "runtime_quick_forecast_policy.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(self.policy)
        self.assertEqual(self.policy["policy_sha256"], self.policy_sha)
        self.assertEqual(self.policy["approved_model"]["model_id"], "random_forest")
        self.assertEqual(self.policy["approved_model"]["parameters_sha256"], "ac37d2d2947de2f6004d39ecdfa3290c5d65901b796f1eb1fd248ad658e1b1e0")
        self.assertEqual(self.policy["candidate_registry_sha256"], self.registry_sha)
        self.assertTrue(self.policy["runtime_upload_permission"])

    def test_exact_compatible_scope_is_eligible_but_outputs_remain_unavailable(self):
        result = runtime_policy.evaluate_quick_forecast_policy(self.policy, self.context())
        self.assertTrue(result["eligible"])
        self.assertEqual(result["approvedModelId"], "random_forest")
        self.assertEqual(result["uncertaintyStatus"], "pending_dataset_specific_calibration")
        self.assertEqual(result["preparednessStatus"], "unavailable_missing_planning_policy")
        serialized = json.dumps(result)
        self.assertNotIn("53", serialized)
        self.assertNotIn("187", serialized)
        self.assertNotIn("87", serialized)
        self.assertNotIn("120", serialized)
        self.assertNotIn("153", serialized)

    def test_every_governed_identity_and_quality_failure_blocks(self):
        cases = [
            (lambda c: c.update(deployment_id="other"), "deployment_mismatch"),
            (lambda c: c["case_geography"].update(geography_id="BGD-OTHER"), "geography_mismatch"),
            (lambda c: c.update(canonical_contract_version="other"), "canonical_contract_mismatch"),
            (lambda c: c.update(feature_order_sha256="0" * 64), "feature_contract_mismatch"),
            (lambda c: c.update(target="other"), "target_mismatch"),
            (lambda c: c.update(horizon_weeks=1), "horizon_mismatch"),
            (lambda c: c["source_metadata"]["cases"].update(source_type="uploaded_real"), "source_type_not_approved"),
            (lambda c: c["source_metadata"]["climate"].update(aggregation_method="daily_mean"), "aggregation_not_approved"),
            (lambda c: c.update(overlap_weeks=110, labelled_rows=103), "insufficient_quick_history"),
            (lambda c: c.update(contiguous_history=False), "non_contiguous_history"),
            (lambda c: c.update(valid_inference_row=False), "invalid_inference_row"),
            (lambda c: c.update(approved_model_id="gradient_boosting"), "approved_model_mismatch"),
            (lambda c: c.update(approved_model_parameters_sha256="0" * 64), "parameter_hash_mismatch"),
            (lambda c: c.update(candidate_registry_sha256="0" * 64), "candidate_registry_mismatch"),
        ]
        for mutation, code in cases:
            with self.subTest(code=code):
                self.assert_blocked(mutation, code)

    def test_inactive_or_disabled_policy_blocks(self):
        for field, value, code in (("policy_status", "inactive", "policy_inactive"),
                                   ("runtime_upload_permission", False, "runtime_upload_not_permitted")):
            policy = copy.deepcopy(self.policy)
            policy[field] = value
            result = runtime_policy.evaluate_quick_forecast_policy(policy, self.context())
            self.assertFalse(result["eligible"])
            self.assertIn(code, result["reasonCodes"])

    def test_policy_evaluator_does_not_write_or_execute(self):
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        runtime_policy.evaluate_quick_forecast_policy(self.policy, self.context())
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (ROOT / "data").glob("*") if path.is_file()}
        self.assertEqual(before, after)
        implementation = (ROOT / "analytics" / "runtime_policy.py").read_text(encoding="utf-8")
        validator = (ROOT / "analytics" / "runtime_validate.py").read_text(encoding="utf-8")
        for forbidden in (".fit(", "build_candidate_comparison", "build_directives", "generate_forecast"):
            self.assertNotIn(forbidden, implementation)
            self.assertNotIn(forbidden, validator)


if __name__ == "__main__":
    unittest.main()
