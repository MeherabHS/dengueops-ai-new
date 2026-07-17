import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_approved_forecast_commit import ApprovedForecastCommitError, commit_approved_forecast


class ApprovedCommitTests(unittest.TestCase):
    def test_incomplete_bundle_cannot_change_latest_or_consume_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            run_id, authorization_id = str(uuid.uuid4()), str(uuid.uuid4())
            staging = root / "staging" / run_id
            (staging / "artifacts").mkdir(parents=True)
            state = root / "authorization-state" / authorization_id
            state.mkdir(parents=True)
            with self.assertRaises(ApprovedForecastCommitError):
                commit_approved_forecast(root, staging, {"runId": run_id, "authorizationId": authorization_id})
            self.assertFalse((root / "deployments/dhaka_south/latest.json").exists())
            self.assertFalse((state / "consumption.json").exists())

    def test_phase_two_commit_recomputes_all_security_critical_evidence(self):
        source = (ROOT / "analytics/runtime_approved_forecast_commit.py").read_text()
        required_checks = (
            "assessmentPolicySha256", "decisionPolicySha256", "candidateRegistrySha256",
            "technicalWinnerParameterSha256", "selectedModelParameterSha256", "successfulFolds",
            "failedFolds", "foldPlanSha256", "selectedEvaluationPeriod", "trainingRowCount",
            "trainingPeriod", "featureMatrixSha256", "featureOrderSha256", "authorizationCommitSha256",
            "forecastOutputSha256", "modelCardSha256", "runRecordSha256", "completeReconciliation",
        )
        for field in required_checks:
            with self.subTest(field=field):
                self.assertIn(field, source)
        self.assertLess(source.rindex('atomic_json(deployment / "latest.json"'), source.rindex('atomic_json(state / "consumption.json"'))
        self.assertNotIn("profile.json", source)


if __name__ == "__main__":
    unittest.main()
