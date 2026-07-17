import unittest
from pathlib import Path

class ForecastOutcomeCommitCoverage(unittest.TestCase):
    def test_commit_module_is_isolated_from_forecast_commit(self):
        source=(Path(__file__).resolve().parent.parent/"analytics/runtime_forecast_outcome_commit.py").read_text()
        self.assertIn("latestForecastPointerModified",source)
        self.assertIn("duplicate_forecast_outcome",source)
        self.assertIn("verify_forecast_source",source)
        self.assertIn("sourceFamilyBreakdowns",source)
        self.assertIn("monitoringPolicyBreakdowns",source)
        self.assertIn("authorizationModified",source)
        self.assertNotIn("atomic_json(latest_path",source)

if __name__=="__main__":unittest.main()
