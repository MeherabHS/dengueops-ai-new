from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from formula_registry import (  # noqa: E402
    FormulaRegistryError, get_formula, load_formula_registry, registry_sha256,
    validate_formula_registry,
)


class FormulaRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = load_formula_registry()

    def test_valid_registry_versions_and_required_active_ids(self):
        self.assertEqual(self.registry["registry_version"], "p1.3-v1")
        self.assertIn("VALIDATION.ROLLING_ORIGIN", {f["formula_id"] for f in self.registry["formulas"]})
        self.assertIn("MODEL.CANDIDATE_COMPARISON", {f["formula_id"] for f in self.registry["formulas"]})
        self.assertIn("MODEL.SELECTED_MODEL_ADOPTION", {f["formula_id"] for f in self.registry["formulas"]})
        self.assertIn("UNCERTAINTY.TEMPORAL_CALIBRATION", {f["formula_id"] for f in self.registry["formulas"]})
        required = {
            "TARGET.HORIZON.2W", "FEATURE.CASE_LAGS", "FEATURE.CLIMATE_LAGS",
            "MODEL.GBR.CONFIG", "FORECAST.GROWTH_FACTOR", "FORECAST.GROWTH_CATEGORY",
            "FORECAST.RMSE_SENSITIVITY", "OPS.EXPOSURE.COMPOSITION",
            "OPS.ADMISSION_FRACTION", "OPS.BED.DEMAND", "OPS.BED.DEFICIT",
            "OPS.STOCK.SDH", "OPS.STOCK.THRESHOLDS", "OPS.PRIORITY.SCORE",
            "OPS.DIRECTIVE.TRIGGERS", "EVIDENCE.FEATURE_IMPORTANCE",
            "POLICY.BENCHMARK.ISOLATION",
        }
        self.assertTrue(required.issubset({f["formula_id"] for f in self.registry["formulas"]}))
        self.assertTrue(all(f["version"] for f in self.registry["formulas"]))
        importance = get_formula("EVIDENCE.FEATURE_IMPORTANCE", self.registry)
        self.assertEqual(importance["version"], "1.1")
        self.assertEqual(importance["deployment_gate"], "research_candidate")
        self.assertFalse(importance["institutional_approval_required"])

    def test_duplicate_unknown_gate_and_invalid_range_fail(self):
        duplicate = copy.deepcopy(self.registry)
        duplicate["formulas"].append(copy.deepcopy(duplicate["formulas"][0]))
        with self.assertRaisesRegex(FormulaRegistryError, "Duplicate formula_id"):
            validate_formula_registry(duplicate)
        bad_gate = copy.deepcopy(self.registry)
        bad_gate["formulas"][0]["deployment_gate"] = "production"
        with self.assertRaisesRegex(FormulaRegistryError, "unknown deployment gate"):
            validate_formula_registry(bad_gate)
        bad_range = copy.deepcopy(self.registry)
        bad_range["formulas"][0]["parameters"]["horizon_weeks"]["value"] = 99
        with self.assertRaisesRegex(FormulaRegistryError, "exceeds its maximum"):
            validate_formula_registry(bad_range)

    def test_unsupported_and_unapproved_cannot_have_high_gate(self):
        for formula_id in ("FORECAST.GROWTH_CATEGORY", "OPS.STOCK.THRESHOLDS"):
            changed = copy.deepcopy(self.registry)
            next(f for f in changed["formulas"] if f["formula_id"] == formula_id)["deployment_gate"] = "operational_advisory"
            with self.assertRaises(FormulaRegistryError):
                validate_formula_registry(changed)

    def test_registry_hash_is_deterministic(self):
        self.assertEqual(registry_sha256(), registry_sha256())
        self.assertEqual(len(registry_sha256()), 64)

    def test_formula_has_complete_governance(self):
        formula = get_formula("OPS.STOCK.THRESHOLDS")
        self.assertEqual(formula["approval_status"], "not_approved")
        self.assertEqual(formula["deployment_gate"], "benchmark_only")


if __name__ == "__main__":
    unittest.main()
