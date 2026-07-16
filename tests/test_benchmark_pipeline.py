from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

import run_pipeline  # noqa: E402
from input_sources import SourcePlanError, resolve_input_plan  # noqa: E402


class BenchmarkPipelineTest(unittest.TestCase):
    def test_source_plan_requires_all_domains_and_has_one_non_demo_producer(self):
        for kwargs in (
            {"case_source": "synthetic_benchmark"},
            {"climate_source": "synthetic_benchmark"},
            {"operational_source": "synthetic_benchmark"},
            {"case_source": "synthetic_benchmark", "climate_source": "synthetic_benchmark"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(SourcePlanError):
                resolve_input_plan(**kwargs)
        plan = resolve_input_plan(case_source="synthetic_benchmark", climate_source="synthetic_benchmark", operational_source="synthetic_benchmark")
        self.assertEqual(len(plan.producers), 1)
        self.assertEqual(plan.producers[0].producer_id, "generate_benchmark_data")
        self.assertEqual(plan.producers[0].domains, ("cases", "climate", "operational"))
        self.assertEqual(plan.demo_domains, ())

    def test_benchmark_options_without_benchmark_sources_fail_before_execution(self):
        with patch.object(run_pipeline, "run_step") as run_step:
            result = run_pipeline.run_pipeline(benchmark_scenario="severe_surge", benchmark_options_explicit=True)
        self.assertEqual(result, 2)
        run_step.assert_not_called()

    def test_current_generated_pipeline_has_expected_origin_provenance_and_features(self):
        manifest_path = ROOT / "data" / "input_manifest.json"
        if not manifest_path.exists():
            self.skipTest("Run benchmark pipeline to exercise artifact integration.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["inputs"]["cases"]["selected_source"] != "synthetic_benchmark":
            self.skipTest("Current artifacts are not benchmark artifacts.")
        for domain in ("cases", "climate", "operational"):
            self.assertEqual(manifest["inputs"][domain]["selected_source"], "synthetic_benchmark")
            self.assertEqual(manifest["inputs"][domain]["adapter_metadata"]["adapter"], "synthetic_benchmark")
        self.assertEqual(manifest["synthetic"], {"seed": 42, "scenario": "normal", "simulation_version": "benchmark-v1", "domains": ["cases", "climate", "operational"]})
        forecast = json.loads((ROOT / "data" / "forecast_output.json").read_text(encoding="utf-8"))
        self.assertEqual((forecast["latest_known_epi_year"], forecast["latest_known_epi_week"]), (2024, 24))
        self.assertEqual((forecast["target_epi_year"], forecast["target_epi_week"]), (2024, 26))
        self.assertEqual(len(forecast["features_used"]), 18)
        self.assertEqual(forecast["forecast_growth_category"], "High forecast growth")
        self.assertEqual(forecast["experimental_growth_score"], 71)
        self.assertNotIn("risk_level", forecast)
        self.assertNotIn("risk_score", forecast)

    def test_canonical_bundle_validation_fails_closed(self):
        good = {
            "forecast_output.json": {
                "forecast_growth_category": "Low forecast growth",
                "experimental_growth_score": 1,
                "preparedness_scenarios": {},
                "uncertainty_scenarios": {},
            },
            "directives.json": {"directives": []},
        }
        run_pipeline._validate_canonical_generated_bundle(good)
        missing = json.loads(json.dumps(good)); del missing["forecast_output.json"]["forecast_growth_category"]
        with self.assertRaisesRegex(ValueError, "missing canonical field"):
            run_pipeline._validate_canonical_generated_bundle(missing)
        legacy = json.loads(json.dumps(good)); legacy["forecast_output.json"]["risk_score"] = 1
        with self.assertRaisesRegex(ValueError, "prohibited legacy"):
            run_pipeline._validate_canonical_generated_bundle(legacy)


if __name__ == "__main__":
    unittest.main()
