from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from evidence_registry import (  # noqa: E402
    EvidenceRegistryError, evidence_registry_sha256, load_evidence_registry,
    validate_evidence_registry,
)


def record(evidence_id: str = "EV.TEST.001") -> dict:
    return {
        "evidence_id": evidence_id, "record_version": "1.0", "record_status": "active",
        "title": "Test record", "source_type": "software_documentation",
        "issuing_organization_or_journal": "Test fixture organization", "publication_year": 2026,
        "geography": "general", "population": "not applicable", "study_design": "documentation fixture",
        "variables": [], "findings_summary": "Test-only registry validation fixture.",
        "formula_ids_supported": [], "applicability": "general_method",
        "limitations": ["Test fixture only."], "local_transferability": "not assessed",
        "verification_status": "unverified", "reviewed_by": None, "review_date": None,
        "document_location": None, "citation_identifier": None,
        "supersedes_evidence_id": None, "content_sha256": None,
    }


class EvidenceRegistryTest(unittest.TestCase):
    def setUp(self):
        self.empty = load_evidence_registry()

    def test_empty_initial_registry_passes_and_does_not_promote_formulas(self):
        self.assertEqual(self.empty["evidence"], [])
        formulas = json.loads((ROOT / "config" / "formulas.json").read_text(encoding="utf-8"))
        self.assertTrue(any(item["evidence_status"] == "missing" for item in formulas["formulas"]))

    def test_duplicate_evidence_ids_fail(self):
        value = copy.deepcopy(self.empty); value["evidence"] = [record(), record()]
        with self.assertRaisesRegex(EvidenceRegistryError, "Duplicate evidence_id"):
            validate_evidence_registry(value)

    def test_controlled_values_fail(self):
        for field, value in (("source_type", "blog"), ("applicability", "global"), ("verification_status", "confirmed")):
            registry = copy.deepcopy(self.empty); item = record(); item[field] = value; registry["evidence"] = [item]
            with self.subTest(field=field), self.assertRaises(EvidenceRegistryError):
                validate_evidence_registry(registry)

    def test_invalid_publication_year_fails(self):
        registry = copy.deepcopy(self.empty); item = record(); item["publication_year"] = 2099; registry["evidence"] = [item]
        with self.assertRaisesRegex(EvidenceRegistryError, "publication_year"):
            validate_evidence_registry(registry)

    def test_verified_metadata_and_local_document_are_required(self):
        registry = copy.deepcopy(self.empty); item = record(); item["verification_status"] = "verified"; registry["evidence"] = [item]
        with self.assertRaisesRegex(EvidenceRegistryError, "reviewed_by"):
            validate_evidence_registry(registry)
        item.update({"reviewed_by": "Reviewer", "review_date": "2026-07-12", "document_location": "docs/missing-evidence.pdf", "citation_identifier": "LOCAL-1", "content_sha256": "0" * 64})
        with self.assertRaisesRegex(EvidenceRegistryError, "does not exist"):
            validate_evidence_registry(registry)

    def test_supersession_cycle_fails(self):
        first, second = record("EV.TEST.001"), record("EV.TEST.002")
        first["supersedes_evidence_id"] = second["evidence_id"]
        second["supersedes_evidence_id"] = first["evidence_id"]
        registry = copy.deepcopy(self.empty); registry["evidence"] = [first, second]
        with self.assertRaisesRegex(EvidenceRegistryError, "cycle"):
            validate_evidence_registry(registry)

    def test_hash_is_exact_and_deterministic(self):
        path = ROOT / "config" / "evidence_registry.json"
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(evidence_registry_sha256(), expected)
        self.assertEqual(evidence_registry_sha256(), evidence_registry_sha256())


if __name__ == "__main__":
    unittest.main()
