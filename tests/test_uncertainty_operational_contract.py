import copy, json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
from operational_engine import build_directives


class UncertaintyOperationalContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.forecast = json.loads((ROOT / "data/forecast_output.json").read_text())
        cls.zones = json.loads((ROOT / "data/zones.json").read_text())
        cls.facilities = json.loads((ROOT / "data/facilities.json").read_text())
        cls.inventory = json.loads((ROOT / "data/inventory.json").read_text())

    def test_planning_triplet_is_authoritative_and_unchanged(self):
        scenarios = self.forecast["preparedness_scenarios"]
        self.assertEqual([scenarios[key]["forecast_cases"] for key in ("best_case", "expected_case", "worst_case")], [87, 120, 153])
        self.assertEqual(self.forecast["uncertainty_scenarios"], scenarios)
        self.assertEqual(self.forecast["preparedness_scenario_method"]["status"], "operational_planning_compatibility_only_not_forecast_interval")

    def test_deprecated_alias_alone_fails_and_empirical_range_does_not_drive_directives(self):
        missing = copy.deepcopy(self.forecast); missing.pop("preparedness_scenarios")
        with self.assertRaises(ValueError): build_directives(missing, self.zones, self.facilities, self.inventory, "benchmark_only")
        changed = copy.deepcopy(self.forecast)
        changed["forecast_uncertainty"]["interval_lower_reported"] = 1
        changed["forecast_uncertainty"]["interval_upper_reported"] = 9999
        output = build_directives(changed, self.zones, self.facilities, self.inventory, "benchmark_only")
        self.assertFalse(output["scenario_policy"]["forecast_empirical_range_drives_directives"])
        self.assertEqual(output["scenario_context"], self.forecast["preparedness_scenarios"])


if __name__ == "__main__": unittest.main()
