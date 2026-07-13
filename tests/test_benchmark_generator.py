from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from benchmark import BenchmarkConfig, generate_benchmark, write_bundle_atomic  # noqa: E402
from benchmark.generate_benchmark_data import CASE_COLUMNS, CLIMATE_COLUMNS  # noqa: E402


class BenchmarkGeneratorTest(unittest.TestCase):
    def publish(self, config=BenchmarkConfig()):
        directory = tempfile.TemporaryDirectory()
        write_bundle_atomic(generate_benchmark(config), directory.name)
        return directory, Path(directory.name)

    def test_default_contract_links_and_period(self):
        bundle = generate_benchmark(BenchmarkConfig())
        cases, climate = bundle["cases"], bundle["climate"]
        self.assertEqual(tuple(cases.columns), CASE_COLUMNS)
        self.assertEqual(tuple(climate.columns), CLIMATE_COLUMNS)
        self.assertEqual(len(cases), 180)
        self.assertEqual((int(cases.iloc[-1].epi_year), int(cases.iloc[-1].epi_week)), (2024, 24))
        self.assertNotIn(53, cases.epi_week.tolist())
        self.assertEqual(set(cases.geography_id), {"BGD-DHAKA-SOUTH"})
        self.assertEqual(len(bundle["zones"]), 5)
        self.assertAlmostEqual(sum(z["population_share"] for z in bundle["zones"]), 1.0)
        self.assertEqual(len(bundle["facilities"]), 10)
        self.assertEqual(len(bundle["inventory"]), 20)
        zones = {z["zone_id"] for z in bundle["zones"]}
        facilities = {f["facility_id"] for f in bundle["facilities"]}
        self.assertTrue(all(f["zone_id"] in zones and f["occupied_dengue_beds_demo"] <= f["dengue_bed_capacity_demo"] <= f["general_bed_capacity"] for f in bundle["facilities"]))
        self.assertTrue(all(i["facility_id"] in facilities for i in bundle["inventory"]))

    def test_same_seed_is_byte_identical_and_different_seed_changes_series(self):
        first, p1 = self.publish()
        second, p2 = self.publish()
        third, p3 = self.publish(BenchmarkConfig(seed=43))
        try:
            for name in ("dengue_cases.csv", "climate_data.csv", "zones.json", "facilities.json", "inventory.json", "benchmark_expectations.json"):
                self.assertEqual((p1 / name).read_bytes(), (p2 / name).read_bytes())
            self.assertNotEqual((p1 / "climate_data.csv").read_bytes(), (p3 / "climate_data.csv").read_bytes())
            self.assertNotEqual((p1 / "dengue_cases.csv").read_bytes(), (p3 / "dengue_cases.csv").read_bytes())
        finally:
            first.cleanup(); second.cleanup(); third.cleanup()

    def test_metadata_hashes_exactly_match_canonical_files(self):
        directory, path = self.publish()
        try:
            metadata = json.loads((path / "raw" / "synthetic_benchmark_metadata.json").read_text(encoding="utf-8"))
            for name, digest in metadata["output_hashes"].items():
                self.assertEqual(hashlib.sha256((path / name).read_bytes()).hexdigest(), digest)
        finally:
            directory.cleanup()

    def test_invalid_configuration_does_not_replace_prior_files(self):
        directory, path = self.publish()
        original = (path / "dengue_cases.csv").read_bytes()
        try:
            with self.assertRaises(ValueError):
                generate_benchmark(BenchmarkConfig(number_of_weeks=103))
            self.assertEqual((path / "dengue_cases.csv").read_bytes(), original)
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
