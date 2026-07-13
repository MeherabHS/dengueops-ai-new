from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from evidence_registry import EvidenceRegistryError, load_evidence_registry, validate_formula_evidence_links  # noqa: E402
from formula_registry import load_formula_registry  # noqa: E402
from tests.test_evidence_registry import record  # noqa: E402


class FormulaEvidenceLinkTest(unittest.TestCase):
    def setUp(self):
        self.evidence = load_evidence_registry()
        self.formulas = load_formula_registry()

    def test_empty_links_are_valid(self):
        validate_formula_evidence_links(self.evidence, self.formulas)

    def test_unknown_formula_from_evidence_fails(self):
        evidence = copy.deepcopy(self.evidence); item = record(); item["formula_ids_supported"] = ["UNKNOWN.FORMULA"]; evidence["evidence"] = [item]
        with self.assertRaisesRegex(EvidenceRegistryError, "unknown formula"):
            validate_formula_evidence_links(evidence, self.formulas)

    def test_unknown_evidence_from_formula_fails(self):
        formulas = copy.deepcopy(self.formulas); formulas["formulas"][0]["evidence_references"] = ["EV.MISSING"]
        with self.assertRaisesRegex(EvidenceRegistryError, "unknown evidence"):
            validate_formula_evidence_links(self.evidence, formulas)

    def test_bidirectional_link_is_required(self):
        evidence = copy.deepcopy(self.evidence); item = record(); item["formula_ids_supported"] = [self.formulas["formulas"][0]["formula_id"]]; evidence["evidence"] = [item]
        with self.assertRaisesRegex(EvidenceRegistryError, "bidirectionally"):
            validate_formula_evidence_links(evidence, self.formulas)


if __name__ == "__main__":
    unittest.main()
