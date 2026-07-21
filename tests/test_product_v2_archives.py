from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ARCHIVES = {
    "config/candidate_models_p1.2a-v1.json": "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4",
    "config/deployments/dhaka_south/assessment_policy_p2-v1.json": "636aecf3f8482283b384e8a20553c61d7263c688476ddbefd34e99c57db8df6b",
    "config/deployments/dhaka_south/decision_policy_p2-v1.json": "6ebde8d161c67ad1a4b31d79363d06093266ff48813c3771dfa3dc7da11723f1",
    "config/deployments/dhaka_south/quick_forecast_policy_p1.4f-v1.json": "02e31f11addfb5e59e1b3d276148bface284383dcd404e2a6370e27cd8e7dd45",
    "config/deployments/dhaka_south/model_lifecycle_policy_p2-v1.json": "c64a78838146c7e076c8ced359585573cc1422c5f754811ba866d079b51905f5",
    "config/deployments/dhaka_south/forecast_outcome_policy_p2-v1.json": "5ea1b4c280363566ece446a50657339b55ed865b4550774d677b4291c34c84c0",
    "config/deployments/dhaka_south/model_degradation_evidence_policy_p2-v1.json": "ffff9421d5475f6b4851949a8c6f4539e2288b51b3b50d5c485533342889404f",
}


class ProductV2ArchiveTests(unittest.TestCase):
    def test_archives_are_byte_identical_to_checkpoint_sources(self):
        for archive, checkpoint_sha in ARCHIVES.items():
            with self.subTest(archive=archive):
                archived = ROOT / archive
                self.assertTrue(archived.is_file())
                self.assertEqual(
                    hashlib.sha256(archived.read_bytes()).hexdigest(),
                    checkpoint_sha,
                )

    def test_archived_identities_remain_historical_and_version_strict(self):
        expected = {
            "candidate_models_p1.2a-v1.json": ("candidate_registry_version", "p1.2a-v1"),
            "assessment_policy_p2-v1.json": ("policy_version", "p2-v1"),
            "decision_policy_p2-v1.json": ("policyVersion", "p2-v1"),
            "quick_forecast_policy_p1.4f-v1.json": ("policy_version", "p1.4f-v1"),
            "model_lifecycle_policy_p2-v1.json": ("policy_version", "p2-v1"),
            "forecast_outcome_policy_p2-v1.json": ("policy_version", "p2-v1"),
            "model_degradation_evidence_policy_p2-v1.json": ("policy_version", "p2-v1"),
        }
        for archive, (field, version) in expected.items():
            path = next(ROOT / relative for relative in ARCHIVES if Path(relative).name == archive)
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value[field], version)
            self.assertNotEqual(version, "p2-v2")


if __name__ == "__main__":
    unittest.main()
