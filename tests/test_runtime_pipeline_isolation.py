import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class RuntimePipelineIsolationTests(unittest.TestCase):
    def test_runtime_modules_do_not_import_prohibited_engines(self):
        combined = "\n".join((ROOT / "analytics" / name).read_text(encoding="utf-8") for name in ("runtime_worker.py", "runtime_quick_forecast.py", "runtime_commit.py"))
        for prohibited in ("run_pipeline", "model_candidates", "uncertainty_engine", "operational_engine", "validation_backtest"):
            self.assertNotIn(f"import {prohibited}", combined)
            self.assertNotIn(f"from {prohibited}", combined)
        self.assertNotIn('ROOT / "data"', combined)


if __name__ == "__main__":
    unittest.main()
