import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))


class ImportOrderTests(unittest.TestCase):

    def test_forward_import_order(self):
        import runtime_model_lifecycle
        import runtime_model_lifecycle_commit
        import runtime_active_model

    def test_reverse_import_order(self):
        import runtime_active_model
        import runtime_model_lifecycle_commit
        import runtime_model_lifecycle


if __name__ == "__main__":
    unittest.main()
