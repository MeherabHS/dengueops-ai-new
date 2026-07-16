from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from formula_registry import (  # noqa: E402
    FormulaRegistryError, assert_formulas_allowed, assert_not_benchmark_formula,
    formula_gate_allows,
)
from operational_engine import OPERATIONAL_FORMULA_IDS, build_directives  # noqa: E402


class DeploymentFormulaGateTest(unittest.TestCase):
    def test_gate_order_and_operational_blockers(self):
        self.assertTrue(formula_gate_allows("MODEL.GBR.CONFIG", "research_candidate"))
        self.assertFalse(formula_gate_allows("OPS.DIRECTIVE.TRIGGERS", "research_candidate"))
        with self.assertRaisesRegex(FormulaRegistryError, "OPS.DIRECTIVE.TRIGGERS"):
            assert_formulas_allowed(OPERATIONAL_FORMULA_IDS, "operational_advisory")

    def test_benchmark_formula_cannot_be_operational(self):
        with self.assertRaisesRegex(FormulaRegistryError, "synthetic_benchmark_only"):
            assert_not_benchmark_formula("POLICY.BENCHMARK.ISOLATION")

    def test_build_directives_blocks_high_gate_and_lists_formula_ids(self):
        data = ROOT / "data"
        values = [json.loads((data / name).read_text(encoding="utf-8")) for name in ("forecast_output.json", "zones.json", "facilities.json", "inventory.json")]
        with self.assertRaises(FormulaRegistryError) as raised:
            build_directives(*values, deployment_gate="institution_approved")
        self.assertIn("FORECAST.GROWTH_FACTOR", str(raised.exception))
        self.assertIn("OPS.DIRECTIVE.TRIGGERS", str(raised.exception))

    def test_benchmark_gate_emits_governed_non_operational_suggestions(self):
        data = ROOT / "data"
        values = [json.loads((data / name).read_text(encoding="utf-8")) for name in ("forecast_output.json", "zones.json", "facilities.json", "inventory.json")]
        result = build_directives(*values, deployment_gate="benchmark_only")
        self.assertNotIn("recommendations", result["directives"][0])
        suggestion = result["directives"][0]["planning_suggestions"][0]
        self.assertEqual(suggestion["approval_status"], "not_approved")
        self.assertEqual(suggestion["deployment_gate"], "benchmark_only")
        self.assertIn("not an operational recommendation", suggestion["disclaimer"])


if __name__ == "__main__":
    unittest.main()
