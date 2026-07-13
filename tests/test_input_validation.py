from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

import generate_demo_data  # noqa: E402
import run_pipeline  # noqa: E402
from forecast_model import advance_epi_week  # noqa: E402
from input_sources import resolve_input_plan  # noqa: E402
from input_validation import (  # noqa: E402
    InputValidationError,
    build_input_manifest,
    validate_case_dataset,
    validate_climate_dataset,
    validate_cross_source_compatibility,
    validate_inputs_and_write_manifest,
    validate_operational_inputs,
    write_manifest_atomic,
)


class InputValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        with contextlib.redirect_stdout(io.StringIO()):
            generate_demo_data.main(output_dir=self.data_dir)
        self.cases_path = self.data_dir / "dengue_cases.csv"
        self.climate_path = self.data_dir / "climate_data.csv"
        self.zones_path = self.data_dir / "zones.json"
        self.facilities_path = self.data_dir / "facilities.json"
        self.inventory_path = self.data_dir / "inventory.json"
        self.manifest_path = self.data_dir / "input_manifest.json"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def case_result(self, expected: str | None = "synthetic_demo"):
        return validate_case_dataset(self.cases_path, expected)

    def climate_result(self, expected: str | None = "synthetic_demo"):
        return validate_climate_dataset(self.climate_path, expected)

    def operational_result(self, expected: str | None = "synthetic_demo"):
        return validate_operational_inputs(
            self.zones_path, self.facilities_path, self.inventory_path, expected
        )

    def mutate_csv(self, path: Path, mutate) -> None:
        frame = pd.read_csv(path)
        mutate(frame)
        frame.to_csv(path, index=False)

    def mutate_json(self, path: Path, mutate) -> None:
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_valid_synthetic_case_and_climate_contracts(self) -> None:
        cases = self.case_result()
        climate = self.climate_result()
        self.assertEqual(cases.status, "passed", cases.errors)
        self.assertEqual(climate.status, "passed", climate.errors)
        self.assertEqual(cases.counts["rows"], 128)
        self.assertEqual(climate.counts["rows"], 128)
        self.assertEqual(cases.geography_id, "BGD-DHAKA-SOUTH")
        self.assertEqual(climate.geography_id, "BGD-DHAKA-SOUTH")

    def test_valid_operational_contract(self) -> None:
        result = self.operational_result()
        self.assertEqual(result.status, "passed", result.errors)
        self.assertEqual(result.counts, {
            "zones": 5, "facilities": 11, "inventory_records": 22
        })

    def test_missing_required_columns_are_rejected(self) -> None:
        self.mutate_csv(self.cases_path, lambda df: df.drop(columns=["cases"], inplace=True))
        self.mutate_csv(self.climate_path, lambda df: df.drop(columns=["humidity_pct"], inplace=True))
        self.assertTrue(any("missing required columns" in e for e in self.case_result().errors))
        self.assertTrue(any("missing required columns" in e for e in self.climate_result().errors))

    def test_duplicate_weekly_key_is_rejected(self) -> None:
        frame = pd.read_csv(self.cases_path)
        pd.concat([frame, frame.iloc[[0]]], ignore_index=True).to_csv(self.cases_path, index=False)
        result = self.case_result()
        self.assertTrue(any("Duplicate" in error for error in result.errors))

    def test_invalid_week_zero_53_and_54_are_rejected(self) -> None:
        for invalid_week in (0, 53, 54):
            with self.subTest(epi_week=invalid_week):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "cases.csv"
                    frame = pd.read_csv(self.cases_path)
                    frame.loc[0, "epi_week"] = invalid_week
                    frame.to_csv(path, index=False)
                    result = validate_case_dataset(path, "synthetic_demo")
                    self.assertTrue(any("between 1 and 52" in e for e in result.errors))

    def test_date_week_mismatch_is_rejected(self) -> None:
        self.mutate_csv(self.cases_path, lambda df: df.__setitem__("date_start", ["2024-01-08", *df["date_start"].iloc[1:]]))
        self.assertTrue(any("mismatch" in e for e in self.case_result().errors))

    def test_negative_cases_and_excess_deaths_are_rejected(self) -> None:
        self.mutate_csv(self.cases_path, lambda df: df.__setitem__("cases", [-1, *df["cases"].iloc[1:]]))
        self.assertTrue(any("nonnegative" in e for e in self.case_result().errors))
        with contextlib.redirect_stdout(io.StringIO()):
            generate_demo_data.main(domains={"cases"}, output_dir=self.data_dir)
        self.mutate_csv(self.cases_path, lambda df: df.__setitem__("deaths", [df.loc[0, "cases"] + 1, *df["deaths"].iloc[1:]]))
        self.assertTrue(any("exceed cases" in e for e in self.case_result().errors))

    def test_invalid_climate_ranges_are_rejected(self) -> None:
        cases = (
            ("rainfall_mm", -1, "nonnegative"),
            ("humidity_pct", -0.1, "between 0 and 100"),
            ("humidity_pct", 100.1, "between 0 and 100"),
        )
        original = pd.read_csv(self.climate_path)
        for column, value, message in cases:
            with self.subTest(column=column, value=value):
                frame = original.copy()
                frame.loc[0, column] = value
                frame.to_csv(self.climate_path, index=False)
                self.assertTrue(any(message in e for e in self.climate_result().errors))

    def test_missing_interior_week_is_rejected(self) -> None:
        frame = pd.read_csv(self.climate_path).drop(index=20).reset_index(drop=True)
        frame.to_csv(self.climate_path, index=False)
        self.assertTrue(any("non-contiguous" in e for e in self.climate_result().errors))

    def test_source_tag_must_match_selection(self) -> None:
        result = validate_case_dataset(self.cases_path, "opendengue")
        self.assertTrue(any("does not match selected source" in e for e in result.errors))

    def test_insufficient_and_valid_104_week_overlap(self) -> None:
        cases = self.case_result()
        climate = self.climate_result()
        operational = self.operational_result()
        short_climate = self.data_dir / "short_climate.csv"
        pd.read_csv(self.climate_path).iloc[:103].to_csv(short_climate, index=False)
        short = validate_climate_dataset(short_climate, "synthetic_demo")
        failed = validate_cross_source_compatibility(cases, short, operational)
        self.assertTrue(any("at least 104" in e for e in failed.errors))

        valid_climate = self.data_dir / "valid_climate.csv"
        pd.read_csv(self.climate_path).iloc[:104].to_csv(valid_climate, index=False)
        valid = validate_climate_dataset(valid_climate, "synthetic_demo")
        passed = validate_cross_source_compatibility(cases, valid, operational)
        self.assertEqual(passed.status, "passed", passed.errors)
        self.assertEqual(passed.overlap_weeks, 104)
        self.assertEqual(passed.expected_supervised_rows, 97)

    def test_geographic_mismatch_is_rejected(self) -> None:
        self.mutate_csv(self.climate_path, lambda df: df.__setitem__("geography_id", "OTHER-CITY"))
        cross = validate_cross_source_compatibility(
            self.case_result(), self.climate_result(), self.operational_result()
        )
        self.assertTrue(any("does not match" in e for e in cross.errors))

    def test_national_city_or_point_mismatch_cannot_be_overridden(self) -> None:
        def national(df):
            df["geography_level"] = "national"
            df["geography_id"] = "BGD"
            df["geography_name"] = "Bangladesh"
        self.mutate_csv(self.cases_path, national)
        for climate_level in ("city", "point"):
            with self.subTest(climate_level=climate_level):
                frame = pd.read_csv(self.climate_path)
                frame["geography_level"] = climate_level
                frame["associated_geography_id"] = "BGD"
                frame.to_csv(self.climate_path, index=False)
                cross = validate_cross_source_compatibility(
                    self.case_result(), self.climate_result(), self.operational_result(),
                    allow_climate_spatial_proxy=True,
                )
                self.assertTrue(any("National case geography" in e for e in cross.errors))

    def test_point_proxy_requires_and_records_acknowledgement(self) -> None:
        def point(df):
            df["geography_level"] = "point"
            df["geography_id"] = "NASA-POINT-DHAKA"
            df["geography_name"] = "Dhaka South centroid"
            df["associated_geography_id"] = "BGD-DHAKA-SOUTH"
        self.mutate_csv(self.climate_path, point)
        inputs = (self.case_result(), self.climate_result(), self.operational_result())
        rejected = validate_cross_source_compatibility(*inputs)
        accepted = validate_cross_source_compatibility(
            *inputs, allow_climate_spatial_proxy=True
        )
        self.assertTrue(any("spatial-proxy" in e for e in rejected.errors))
        self.assertEqual(accepted.status, "passed", accepted.errors)
        self.assertIn("allow_climate_spatial_proxy", accepted.overrides)

    def test_mixed_epidemiology_requires_acknowledgement(self) -> None:
        self.mutate_csv(self.climate_path, lambda df: df.__setitem__("source_type", "nasa_power"))
        inputs = (self.case_result(), self.climate_result(expected=None), self.operational_result())
        rejected = validate_cross_source_compatibility(*inputs)
        accepted = validate_cross_source_compatibility(
            *inputs, allow_mixed_epidemiology_inputs=True
        )
        self.assertTrue(any("mixed-epidemiology" in e for e in rejected.errors))
        self.assertEqual(accepted.status, "passed", accepted.errors)
        self.assertIn("allow_mixed_epidemiology_inputs", accepted.overrides)

    def test_real_epidemiology_with_synthetic_operations_requires_acknowledgement(self) -> None:
        self.mutate_csv(self.cases_path, lambda df: df.__setitem__("source_type", "opendengue"))
        self.mutate_csv(self.climate_path, lambda df: df.__setitem__("source_type", "nasa_power"))
        inputs = (
            self.case_result(expected=None),
            self.climate_result(expected=None),
            self.operational_result(),
        )
        rejected = validate_cross_source_compatibility(*inputs)
        accepted = validate_cross_source_compatibility(
            *inputs, acknowledge_synthetic_operational_data=True
        )
        self.assertTrue(any("synthetic-operational" in e for e in rejected.errors))
        self.assertEqual(accepted.status, "passed", accepted.errors)
        self.assertIn("acknowledge_synthetic_operational_data", accepted.overrides)

    def test_operational_capacity_and_foreign_key_errors(self) -> None:
        mutations = (
            (self.facilities_path, lambda rows: rows[0].__setitem__("occupied_dengue_beds_demo", rows[0]["dengue_bed_capacity_demo"] + 1), "occupancy exceeds"),
            (self.facilities_path, lambda rows: rows[0].__setitem__("dengue_bed_capacity_demo", rows[0]["general_bed_capacity"] + 1), "exceeds general"),
            (self.facilities_path, lambda rows: rows[0].__setitem__("zone_id", "MISSING"), "existing zone"),
            (self.inventory_path, lambda rows: rows[0].__setitem__("facility_id", "MISSING"), "reference a facility"),
        )
        originals = {
            self.facilities_path: self.facilities_path.read_text(encoding="utf-8"),
            self.inventory_path: self.inventory_path.read_text(encoding="utf-8"),
        }
        for path, mutation, message in mutations:
            with self.subTest(message=message):
                for original_path, content in originals.items():
                    original_path.write_text(content, encoding="utf-8")
                self.mutate_json(path, mutation)
                self.assertTrue(any(message in e for e in self.operational_result().errors))

    def test_invalid_inventory_values_are_rejected(self) -> None:
        fields = (("current_stock", -1), ("baseline_daily_consumption", -1), ("reorder_threshold_days", 0))
        original = self.inventory_path.read_text(encoding="utf-8")
        for field_name, value in fields:
            with self.subTest(field=field_name):
                self.inventory_path.write_text(original, encoding="utf-8")
                self.mutate_json(self.inventory_path, lambda rows, f=field_name, v=value: rows[0].__setitem__(f, v))
                self.assertTrue(any(field_name in e for e in self.operational_result().errors))

    def test_manifest_hashes_run_metadata_and_overrides(self) -> None:
        plan = resolve_input_plan()
        manifest = validate_inputs_and_write_manifest(
            plan,
            cases_path=self.cases_path,
            climate_path=self.climate_path,
            zones_path=self.zones_path,
            facilities_path=self.facilities_path,
            inventory_path=self.inventory_path,
            manifest_path=self.manifest_path,
        )
        self.assertEqual(manifest["schema_version"], "1.0")
        self.assertRegex(manifest["run_id"], r"^[0-9a-f-]{36}$")
        self.assertTrue(manifest["created_at"].endswith("Z"))
        self.assertEqual(manifest["cross_source_validation"]["overlap_weeks"], 128)
        self.assertEqual(manifest["overrides"], [])
        case_file = manifest["inputs"]["cases"]["files"][0]
        expected_hash = hashlib.sha256(self.cases_path.read_bytes()).hexdigest()
        self.assertEqual(case_file["sha256"], expected_hash)
        self.assertEqual(json.loads(self.manifest_path.read_text()), manifest)

    def test_manifest_records_used_override(self) -> None:
        self.mutate_csv(self.climate_path, lambda df: df.__setitem__("source_type", "nasa_power"))
        plan = resolve_input_plan()
        # Reused files derive their source classes from canonical row tags.
        reuse = resolve_input_plan(skip_data_generation=True)
        manifest = validate_inputs_and_write_manifest(
            reuse,
            cases_path=self.cases_path,
            climate_path=self.climate_path,
            zones_path=self.zones_path,
            facilities_path=self.facilities_path,
            inventory_path=self.inventory_path,
            manifest_path=self.manifest_path,
            allow_mixed_epidemiology_inputs=True,
        )
        self.assertIn("allow_mixed_epidemiology_inputs", manifest["overrides"])
        self.assertEqual(plan.case_source, "synthetic_demo")

    def test_atomic_manifest_failure_preserves_existing_file(self) -> None:
        self.manifest_path.write_text('{"old": true}\n', encoding="utf-8")
        with patch("input_validation.os.replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                write_manifest_atomic({"new": True}, self.manifest_path)
        self.assertEqual(self.manifest_path.read_text(encoding="utf-8"), '{"old": true}\n')
        self.assertEqual(list(self.data_dir.glob(".input_manifest.json.*.tmp")), [])

    def test_validation_failure_does_not_publish_manifest(self) -> None:
        self.manifest_path.write_text('{"old": true}\n', encoding="utf-8")
        self.mutate_csv(self.cases_path, lambda df: df.__setitem__("cases", [-1, *df["cases"].iloc[1:]]))
        with self.assertRaises(InputValidationError):
            validate_inputs_and_write_manifest(
                resolve_input_plan(), cases_path=self.cases_path,
                climate_path=self.climate_path, zones_path=self.zones_path,
                facilities_path=self.facilities_path, inventory_path=self.inventory_path,
                manifest_path=self.manifest_path,
            )
        self.assertEqual(self.manifest_path.read_text(encoding="utf-8"), '{"old": true}\n')

    def test_pipeline_stage_order_places_validation_before_features(self) -> None:
        plan = resolve_input_plan()
        steps = (
            run_pipeline.build_input_steps(plan)
            + [run_pipeline.build_input_validation_step()]
            + run_pipeline.ANALYTICS_STEPS
        )
        ids = [step["id"] for step in steps]
        self.assertLess(ids.index("generate_demo_data"), ids.index("input_validation"))
        self.assertLess(ids.index("input_validation"), ids.index("feature_engineering"))

    def test_invalid_input_stops_pipeline_before_feature_engineering(self) -> None:
        failure = InputValidationError(["[cases] cases must be nonnegative."])
        with (
            patch.object(run_pipeline, "validate_inputs_and_write_manifest", side_effect=failure),
            patch.object(run_pipeline, "run_step") as run_step,
            patch.object(run_pipeline, "_save_run_summary"),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = run_pipeline.run_pipeline(skip_data_generation=True)
        self.assertEqual(result, 1)
        run_step.assert_not_called()

    def test_default_validation_creates_passing_manifest(self) -> None:
        manifest = validate_inputs_and_write_manifest(
            resolve_input_plan(),
            cases_path=self.cases_path,
            climate_path=self.climate_path,
            zones_path=self.zones_path,
            facilities_path=self.facilities_path,
            inventory_path=self.inventory_path,
            manifest_path=self.manifest_path,
        )
        self.assertEqual(manifest["cross_source_validation"]["status"], "passed")
        for domain in ("cases", "climate", "operational"):
            self.assertEqual(manifest["inputs"][domain]["validation"]["status"], "passed")

    def test_p01_w24_to_w26_and_p02a_single_producer_regressions(self) -> None:
        cases = pd.read_csv(self.cases_path)
        latest = cases.iloc[-1]
        self.assertEqual((int(latest.epi_year), int(latest.epi_week)), (2026, 24))
        self.assertEqual(advance_epi_week(2026, 24, 2), (2026, 26))
        plans = (
            resolve_input_plan(),
            resolve_input_plan(case_source="opendengue"),
            resolve_input_plan(climate_source="nasa_power"),
        )
        for plan in plans:
            for domain in ("cases", "climate", "operational"):
                self.assertEqual(sum(domain in p.domains for p in plan.producers), 1)


if __name__ == "__main__":
    unittest.main()
