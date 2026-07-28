import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_forecast_outcome import execute as execute_outcome
from runtime_model_degradation_source import (
    ModelDegradationSourceError,
    verify_model_degradation_snapshot,
    verify_model_degradation_source,
)
from tests.test_runtime_forecast_outcome import build_outcome_job
from tests.test_runtime_quick_forecast import (
    build_ready_runtime,
    execute_historical_quick_forecast,
)


class RuntimeModelDegradationSourceTests(unittest.TestCase):
    def test_exact_current_monitoring_snapshot_and_hashes_are_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime, workspace, forecast_path, forecast_job = build_ready_runtime(Path(directory))
            execute_historical_quick_forecast(runtime, workspace, forecast_path, forecast_job)
            outcome_job, outcome_path = build_outcome_job(
                runtime,
                forecast_job,
                record_id="degradation-source",
                schema_version="2.1",
            )
            execute_outcome(
                SimpleNamespace(
                    runtime_root=str(runtime),
                    job_record=str(outcome_path),
                    staging=str(runtime / "outcome-staging" / outcome_job["outcomeId"]),
                )
            )
            latest_path = runtime / "deployments/dhaka_south/monitoring/latest.json"
            raw = latest_path.read_bytes()
            pointer = json.loads(raw)
            summary_path = runtime / pointer["monitoringSummaryPath"]
            summary = json.loads(summary_path.read_text())
            verified = verify_model_degradation_source(
                runtime,
                hashlib.sha256(raw).hexdigest(),
                hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                summary["outcomeSetSha256"],
                "p2-v3",
            )
            self.assertEqual(verified["latestBytes"], raw)
            self.assertEqual(verified["latest"]["schemaVersion"], "2.1")
            self.assertEqual(verified["latest"]["policyVersion"], "p2-v3")
            self.assertEqual(len(verified["outcomes"]), verified["summary"]["evaluatedForecastCount"])

            tampered = json.loads(raw)
            tampered["policyVersion"] = "p2-v1"
            with self.assertRaises(ModelDegradationSourceError):
                verify_model_degradation_snapshot(
                    runtime,
                    json.dumps(tampered).encode(),
                    monitoring_policy_version="p2-v3",
                )
            with self.assertRaises(ModelDegradationSourceError):
                verify_model_degradation_snapshot(
                    runtime,
                    raw,
                    monitoring_policy_version="p2-v1",
                )


if __name__ == "__main__":
    unittest.main()
