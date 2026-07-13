import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))
SPEC = importlib.util.spec_from_file_location("runtime_validate", ROOT / "analytics" / "runtime_validate.py")
runtime_validate = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(runtime_validate)


class RuntimeDatasetIdentityTests(unittest.TestCase):
    def test_identity_is_deterministic_and_context_bound(self):
        feature_hash = "a" * 64
        first = runtime_validate.compute_dataset_id(b"cases", b"climate", "dhaka_south", feature_hash)
        self.assertEqual(first, runtime_validate.compute_dataset_id(b"cases", b"climate", "dhaka_south", feature_hash))
        self.assertNotEqual(first, runtime_validate.compute_dataset_id(b"changed", b"climate", "dhaka_south", feature_hash))
        self.assertNotEqual(first, runtime_validate.compute_dataset_id(b"cases", b"changed", "dhaka_south", feature_hash))
        self.assertNotEqual(first, runtime_validate.compute_dataset_id(b"cases", b"climate", "other", feature_hash))

    def test_normalization_can_change_original_hash_without_losing_binding(self):
        payload = b"\xef\xbb\xbfepi_year,epi_week\r\n2024,1\r\n"
        canonical = b"epi_year,epi_week\n2024,1\n"
        self.assertNotEqual(runtime_validate.sha256_bytes(payload), runtime_validate.sha256_bytes(canonical))


if __name__ == "__main__":
    unittest.main()
