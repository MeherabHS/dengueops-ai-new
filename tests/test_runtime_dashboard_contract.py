import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent


def resolve_local_ref(schema, branch):
    reference = branch.get("$ref")
    if reference is None:
        return branch
    if not reference.startswith("#/"):
        raise AssertionError(f"Only local schema references are supported: {reference}")
    resolved = schema
    for token in reference[2:].split("/"):
        resolved = resolved[token.replace("~1", "/").replace("~0", "~")]
    return resolved


def assert_strict_object_dispatch(test_case, schema, branch, label):
    resolved = resolve_local_ref(schema, branch)
    if resolved.get("type") == "object":
        test_case.assertIs(resolved.get("additionalProperties"), False, label)
        return
    nested = resolved.get("oneOf")
    if nested is not None:
        test_case.assertTrue(nested, label)
        for index, child in enumerate(nested):
            assert_strict_object_dispatch(test_case, schema, child, f"{label}.{index}")
        return
    test_case.fail(f"{label} is not a closed object branch or a oneOf dispatch")


class RuntimeDashboardContractTests(unittest.TestCase):
    def test_runtime_schemas_are_strict_at_top_level(self):
        for name in ("runtime_job", "runtime_run", "runtime_commit", "runtime_latest", "runtime_forecast_output", "runtime_forecast_calibration", "runtime_forecast_uncertainty", "runtime_model_card", "runtime_dashboard_summary"):
            schema = json.loads((ROOT / "config" / f"{name}.schema.json").read_text())
            Draft202012Validator.check_schema(schema)
            branches = schema.get("oneOf")
            if branches is None:
                self.assertEqual(schema.get("type"), "object", name)
                self.assertIs(schema.get("additionalProperties"), False, name)
                continue
            self.assertTrue(branches, name)
            for index, branch in enumerate(branches):
                with self.subTest(schema=name, branch=index):
                    assert_strict_object_dispatch(self, schema, branch, f"{name}.{index}")


if __name__ == "__main__":
    unittest.main()
