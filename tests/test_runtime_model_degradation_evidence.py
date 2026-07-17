import hashlib,json,sys,tempfile,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"analytics"))
from runtime_quick_forecast import execute as execute_forecast
from runtime_forecast_outcome import execute as execute_outcome
from runtime_model_degradation_evidence import execute as execute_degradation
from runtime_model_degradation_policy import load_and_validate_model_degradation_policy
from tests.test_runtime_quick_forecast import build_ready_runtime,iso_now
from tests.test_runtime_forecast_outcome import build_outcome_job

def degradation_job(runtime,evidence_id=None):
    latest=runtime/"deployments/dhaka_south/monitoring/latest.json";pointer=json.loads(latest.read_text());summary=runtime/pointer["monitoringSummaryPath"];policy,digest=load_and_validate_model_degradation_policy();job_id=str(uuid.uuid4());evidence_id=evidence_id or str(uuid.uuid4());created=iso_now();job={"schemaVersion":"1.0","jobKind":"degradation_evidence","jobId":job_id,"evidenceId":evidence_id,"deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"workflowMode":"degradation_evidence","policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":digest,"expectedMonitoringLatestSha256":hashlib.sha256(latest.read_bytes()).hexdigest(),"expectedMonitoringSummarySha256":hashlib.sha256(summary.read_bytes()).hexdigest(),"expectedIncludedOutcomeSetSha256":json.loads(summary.read_text())["outcomeSetSha256"],"evidenceOnlyAcknowledged":True,"status":"running","progress":"verifying_monitoring_snapshot","createdAt":created,"claimedAt":created,"startedAt":created,"updatedAt":created,"completedAt":None,"heartbeatAt":created,"workerId":"test","processId":None,"timeoutSeconds":120,"retryCount":0,"error":None,"committedEvidenceId":None};path=runtime/"jobs/running"/f"{job_id}.json";path.write_text(json.dumps(job));return job,path

class RuntimeModelDegradationEvidenceTests(unittest.TestCase):
    def test_quick_snapshot_commits_disabled_window_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime,workspace,forecast_path,forecast_job=build_ready_runtime(Path(directory))
            execute_forecast(SimpleNamespace(runtime_root=str(runtime),job_record=str(forecast_path),workspace=str(workspace),staging=str(runtime/"staging"/forecast_job["runId"])))
            outcome_job,outcome_path=build_outcome_job(runtime,forecast_job,record_id="degradation-quick")
            execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(outcome_path),staging=str(runtime/"outcome-staging"/outcome_job["outcomeId"])))
            monitoring_before=(runtime/"deployments/dhaka_south/monitoring/latest.json").read_bytes();forecast_before=(runtime/"deployments/dhaka_south/latest.json").read_bytes()
            job,path=degradation_job(runtime)
            result=execute_degradation(SimpleNamespace(runtime_root=str(runtime),job_record=str(path),staging=str(runtime/"degradation-staging"/job["evidenceId"])))
            evidence=json.loads((runtime/"degradation-evidence"/job["evidenceId"]/"artifacts/degradation_evidence.json").read_text())
            self.assertFalse(result["recovered"]);self.assertEqual(evidence["cohorts"][0]["monitoringWindow"]["status"],"window_size_not_governed");self.assertFalse(evidence["cohorts"][0]["monitoringWindow"]["metricsCalculated"]);self.assertEqual(evidence["cohorts"][0]["assessmentReferenceStatus"],"not_applicable_no_assessment_reference")
            second,second_path=degradation_job(runtime)
            recovered=execute_degradation(SimpleNamespace(runtime_root=str(runtime),job_record=str(second_path),staging=str(runtime/"degradation-staging"/second["evidenceId"])))
            self.assertTrue(recovered["recovered"]);self.assertEqual(recovered["commit"]["evidenceId"],job["evidenceId"]);self.assertEqual(monitoring_before,(runtime/"deployments/dhaka_south/monitoring/latest.json").read_bytes());self.assertEqual(forecast_before,(runtime/"deployments/dhaka_south/latest.json").read_bytes())
if __name__=="__main__":unittest.main()
