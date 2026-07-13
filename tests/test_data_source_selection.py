from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

import generate_demo_data  # noqa: E402
import fetch_opendengue  # noqa: E402
import run_pipeline  # noqa: E402
from feature_engineering import build_features, build_inference_features  # noqa: E402
from forecast_model import generate_forecast, train_final_model  # noqa: E402
from input_sources import SourcePlanError, resolve_input_plan  # noqa: E402


class SourcePlanTest(unittest.TestCase):
    def test_default_plan_selects_one_synthetic_producer_per_domain(self) -> None:
        plan = resolve_input_plan()

        self.assertEqual(plan.case_source, "synthetic_demo")
        self.assertEqual(plan.climate_source, "synthetic_demo")
        self.assertEqual(plan.operational_source, "synthetic_demo")
        self.assertEqual(plan.demo_domains, ("cases", "climate", "operational"))
        self.assertEqual(len(plan.producers), 1)
        self.assertEqual(plan.producers[0].domains, plan.demo_domains)

    def test_explicit_all_synthetic_matches_default(self) -> None:
        explicit = resolve_input_plan(
            case_source="synthetic_demo",
            climate_source="synthetic_demo",
            operational_source="synthetic_demo",
        )
        self.assertEqual(explicit, resolve_input_plan())

    def test_opendengue_is_only_case_writer(self) -> None:
        plan = resolve_input_plan(case_source="opendengue")
        self.assertEqual(plan.producer_for_domain("cases"), "fetch_opendengue")
        self.assertNotIn("cases", plan.demo_domains)
        self.assertEqual(plan.demo_domains, ("climate", "operational"))

    def test_nasa_power_is_only_climate_writer(self) -> None:
        plan = resolve_input_plan(climate_source="nasa_power")
        self.assertEqual(
            plan.producer_for_domain("climate"), "fetch_nasa_power_climate"
        )
        self.assertNotIn("climate", plan.demo_domains)
        self.assertEqual(plan.demo_domains, ("cases", "operational"))

    def test_combined_real_sources_leave_only_operational_demo(self) -> None:
        plan = resolve_input_plan(
            case_source="opendengue",
            climate_source="nasa_power",
        )
        self.assertEqual(plan.demo_domains, ("operational",))
        self.assertEqual(plan.producer_for_domain("cases"), "fetch_opendengue")
        self.assertEqual(
            plan.producer_for_domain("climate"), "fetch_nasa_power_climate"
        )
        self.assertEqual(
            plan.producer_for_domain("operational"), "generate_demo_data"
        )

    def test_legacy_aliases_map_and_warn(self) -> None:
        cases = resolve_input_plan(use_opendengue=True)
        climate = resolve_input_plan(use_nasa_power_climate=True)

        self.assertEqual(cases.case_source, "opendengue")
        self.assertIn("--use-opendengue is deprecated", cases.warnings[0])
        self.assertEqual(climate.climate_source, "nasa_power")
        self.assertIn("--use-nasa-power-climate is deprecated", climate.warnings[0])

    def test_matching_legacy_and_explicit_source_is_accepted(self) -> None:
        plan = resolve_input_plan(
            case_source="opendengue",
            use_opendengue=True,
        )
        self.assertEqual(plan.case_source, "opendengue")
        self.assertEqual(len(plan.warnings), 1)

    def test_conflicting_legacy_and_explicit_sources_fail(self) -> None:
        with self.assertRaisesRegex(SourcePlanError, "conflicts"):
            resolve_input_plan(
                case_source="synthetic_demo",
                use_opendengue=True,
            )
        with self.assertRaisesRegex(SourcePlanError, "conflicts"):
            resolve_input_plan(
                climate_source="synthetic_demo",
                use_nasa_power_climate=True,
            )

    def test_skip_generation_rejects_all_source_options(self) -> None:
        selections = (
            {"case_source": "synthetic_demo"},
            {"climate_source": "synthetic_demo"},
            {"operational_source": "synthetic_demo"},
            {"use_opendengue": True},
            {"use_nasa_power_climate": True},
        )
        for selection in selections:
            with self.subTest(selection=selection):
                with self.assertRaisesRegex(SourcePlanError, "cannot be combined"):
                    resolve_input_plan(skip_data_generation=True, **selection)

        reuse = resolve_input_plan(skip_data_generation=True)
        self.assertTrue(reuse.reuse_existing)
        self.assertEqual(reuse.producers, ())

    def test_reserved_benchmark_fails_before_producer_execution(self) -> None:
        for option in ("case_source", "climate_source"):
            with self.subTest(option=option):
                with self.assertRaisesRegex(
                    SourcePlanError, "recognized but not implemented"
                ):
                    resolve_input_plan(**{option: "synthetic_benchmark"})

        with patch.object(run_pipeline, "run_step") as run_step:
            result = run_pipeline.run_pipeline(case_source="synthetic_benchmark")
        self.assertEqual(result, 2)
        run_step.assert_not_called()

    def test_empty_opendengue_fetch_fails_despite_stale_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stale_output = Path(temp_dir) / "dengue_cases.csv"
            stale_output.write_text("stale output\n", encoding="utf-8")
            with (
                patch.object(fetch_opendengue, "OUT_FILE", str(stale_output)),
                patch.object(fetch_opendengue, "download_raw", return_value=[]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                result = fetch_opendengue.main()
            self.assertEqual(result, 1)
            self.assertEqual(
                stale_output.read_text(encoding="utf-8"), "stale output\n"
            )

    def test_each_active_plan_has_exactly_one_producer_per_domain(self) -> None:
        plans = (
            resolve_input_plan(),
            resolve_input_plan(case_source="opendengue"),
            resolve_input_plan(climate_source="nasa_power"),
            resolve_input_plan(
                case_source="opendengue", climate_source="nasa_power"
            ),
        )
        for plan in plans:
            with self.subTest(plan=plan):
                for domain in ("cases", "climate", "operational"):
                    owners = [p for p in plan.producers if domain in p.domains]
                    self.assertEqual(len(owners), 1)


class SelectiveDemoGenerationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.output_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def generate(self, domains: set[str]) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            generate_demo_data.main(domains=domains, output_dir=self.output_dir)

    def test_selective_generation_does_not_modify_unselected_cases(self) -> None:
        path = self.output_dir / "dengue_cases.csv"
        sentinel = b"external case producer\n"
        path.write_bytes(sentinel)

        self.generate({"climate", "operational"})

        self.assertEqual(path.read_bytes(), sentinel)
        self.assertTrue((self.output_dir / "climate_data.csv").exists())
        self.assertTrue((self.output_dir / "facilities.json").exists())

    def test_selective_generation_does_not_modify_unselected_climate(self) -> None:
        path = self.output_dir / "climate_data.csv"
        sentinel = b"external climate producer\n"
        path.write_bytes(sentinel)

        self.generate({"cases", "operational"})

        self.assertEqual(path.read_bytes(), sentinel)
        self.assertTrue((self.output_dir / "dengue_cases.csv").exists())
        self.assertTrue((self.output_dir / "inventory.json").exists())

    def test_default_synthetic_inputs_preserve_w24_to_w26_forecast(self) -> None:
        self.generate({"cases", "climate", "operational"})
        cases = self.output_dir / "dengue_cases.csv"
        climate = self.output_dir / "climate_data.csv"
        training, _ = build_features(cases, climate, output_path=None)
        inference = build_inference_features(cases, climate)
        model = train_final_model(training)
        forecast = generate_forecast(training, inference.iloc[-1], model)

        self.assertEqual(
            (int(inference.iloc[-1]["epi_year"]), int(inference.iloc[-1]["epi_week"])),
            (2026, 24),
        )
        self.assertEqual(
            (forecast["latest_known_epi_year"], forecast["latest_known_epi_week"]),
            (2026, 24),
        )
        self.assertEqual(
            (forecast["target_epi_year"], forecast["target_epi_week"]),
            (2026, 26),
        )
        self.assertEqual(forecast["horizon_days"], 14)


if __name__ == "__main__":
    unittest.main()
