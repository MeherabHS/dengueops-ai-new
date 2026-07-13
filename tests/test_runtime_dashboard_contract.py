import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent


class RuntimeDashboardContractTests(unittest.TestCase):
    def test_runtime_schemas_are_strict_at_top_level(self):
        for name in ("runtime_job", "runtime_run", "runtime_commit", "runtime_latest", "runtime_forecast_output", "runtime_forecast_uncertainty", "runtime_model_card", "runtime_dashboard_summary"):
            schema = json.loads((ROOT / "config" / f"{name}.schema.json").read_text())
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema.get("additionalProperties", True), name)


if __name__ == "__main__":
    unittest.main()
