from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from benchmark import BenchmarkConfig, INVALID_SUBTYPES, apply_scenario, generate_benchmark, validate_bundle  # noqa: E402


class BenchmarkScenarioTest(unittest.TestCase):
    def bundle(self, scenario: str):
        return generate_benchmark(apply_scenario(BenchmarkConfig(), scenario))

    def test_all_valid_scenarios_pass_canonical_validation(self):
        for scenario in ("normal", "early_surge", "severe_surge", "facility_pressure", "stock_stress", "replenishment", "reporting_delay"):
            with self.subTest(scenario=scenario):
                validate_bundle(self.bundle(scenario))

    def test_relative_scenario_signals(self):
        normal = self.bundle("normal")
        early = self.bundle("early_surge")
        severe = self.bundle("severe_surge")
        facility = self.bundle("facility_pressure")
        stock = self.bundle("stock_stress")
        replenish = self.bundle("replenishment")
        normal_peak = int(normal["cases"].loc[normal["cases"].cases.idxmax(), "epi_week"])
        early_peak = int(early["cases"].loc[early["cases"].cases.idxmax(), "epi_week"])
        self.assertLessEqual(early_peak, normal_peak - 5)
        self.assertGreater(severe["cases"].cases.max(), normal["cases"].cases.max())
        self.assertGreater(sum(f["occupied_dengue_beds_demo"] / f["dengue_bed_capacity_demo"] for f in facility["facilities"]), sum(f["occupied_dengue_beds_demo"] / f["dengue_bed_capacity_demo"] for f in normal["facilities"]))
        self.assertLess(sum(i["current_stock"] for i in stock["inventory"]), sum(i["current_stock"] for i in normal["inventory"]))
        self.assertGreater(sum(i["current_stock"] for i in replenish["inventory"]), sum(i["current_stock"] for i in normal["inventory"]))

    def test_reporting_delay_preserves_weeks_and_matches_rule(self):
        delayed = self.bundle("reporting_delay")
        latent = delayed["latent_cases"]
        config = delayed["config"]
        self.assertEqual(len(delayed["cases"]), 180)
        self.assertTrue((delayed["cases"].cases >= 0).all())
        for index in (0, 25, 100, 179):
            prior = latent[max(0, index - config.reporting_delay_weeks)]
            expected = round(config.current_reporting_fraction * latent[index] + config.delayed_fraction * prior)
            self.assertEqual(int(delayed["cases"].iloc[index].cases), expected)

    def test_each_invalid_subtype_is_rejected_and_only_one_is_allowed(self):
        for subtype in INVALID_SUBTYPES:
            config = apply_scenario(BenchmarkConfig(invalid_subtype=subtype), "messy_invalid")
            bundle = generate_benchmark(config)
            with self.subTest(subtype=subtype), self.assertRaises(ValueError):
                validate_bundle(bundle)
        with self.assertRaises(ValueError):
            generate_benchmark(BenchmarkConfig(scenario="messy_invalid"))
        with self.assertRaises(ValueError):
            generate_benchmark(BenchmarkConfig(scenario="normal", invalid_subtype="negative_cases"))


if __name__ == "__main__":
    unittest.main()
