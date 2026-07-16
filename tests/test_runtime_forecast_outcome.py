import hashlib
import json
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/"analytics"))
from runtime_forecast_outcome import execute as execute_outcome
from runtime_forecast_outcome_commit import ForecastOutcomeCommitError
from runtime_forecast_outcome_policy import load_and_validate_forecast_outcome_policy
from runtime_quick_forecast import execute as execute_forecast
from tests.test_runtime_quick_forecast import build_ready_runtime, iso_now

def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def build_outcome_job(runtime:Path,forecast_job:dict,record_id="observation-1",outcome_id=None,observed=123):
    run=runtime/"runs"/forecast_job["runId"]
    forecast=json.loads((run/"artifacts/forecast_output.json").read_text())
    commit_sha=hashlib.sha256((run/"metadata/commit.json").read_bytes()).hexdigest()
    policy,digest=load_and_validate_forecast_outcome_policy("dhaka_south")
    observation={"deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"targetColumn":"target_cases_next_2w","forecastHorizonWeeks":2,"forecastTargetPeriod":forecast["targetPeriod"],"observedRaw":observed,"observationSourceType":"synthetic_benchmark","observationSourceId":"dhaka_south_synthetic_benchmark","observationRecordId":record_id,"observationRecordedAt":iso_now(),"limitationsAcknowledged":True}
    job_id=str(uuid.uuid4());outcome_id=outcome_id or str(uuid.uuid4());created=iso_now()
    job={"schemaVersion":"1.0","jobKind":"forecast_outcome","jobId":job_id,"outcomeId":outcome_id,"forecastRunId":forecast_job["runId"],"expectedForecastCommitSha256":commit_sha,"observation":observation,"observationPayloadSha256":canonical_sha(observation),"operatorIdentifier":"test-operator","deploymentId":"dhaka_south","workflowMode":"forecast_outcome_monitoring","policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":digest,"status":"running","progress":"validating_forecast_commit","createdAt":created,"claimedAt":created,"startedAt":created,"updatedAt":created,"completedAt":None,"heartbeatAt":created,"workerId":"test","processId":None,"timeoutSeconds":120,"retryCount":0,"error":None,"committedOutcomeId":None}
    path=runtime/"jobs/running"/f"{job_id}.json";path.write_text(json.dumps(job),encoding="utf-8")
    return job,path

class RuntimeForecastOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.runtime,cls.workspace,cls.forecast_job_path,cls.forecast_job=build_ready_runtime(Path(cls.temp.name))
        execute_forecast(SimpleNamespace(runtime_root=str(cls.runtime),job_record=str(cls.forecast_job_path),workspace=str(cls.workspace),staging=str(cls.runtime/"staging"/cls.forecast_job["runId"])))
        cls.forecast_root=cls.runtime/"runs"/cls.forecast_job["runId"]
        cls.before={str(p.relative_to(cls.forecast_root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in cls.forecast_root.rglob("*") if p.is_file()}

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_01_successful_immutable_outcome_and_monitoring_commit(self):
        job,path=build_outcome_job(self.runtime,self.forecast_job)
        result=execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(path),staging=str(self.runtime/"outcome-staging"/job["outcomeId"])))
        root=self.runtime/"forecast-outcomes"/job["outcomeId"]
        outcome=json.loads((root/"artifacts/outcome_evaluation.json").read_text());summary=json.loads((root/"artifacts/monitoring_summary.json").read_text());commit=json.loads((root/"metadata/commit.json").read_text());pointer=json.loads((self.runtime/"deployments/dhaka_south/monitoring/latest.json").read_text())
        self.assertFalse(result["recovered"]);self.assertEqual(outcome["signedError"],123-outcome["forecastRaw"])
        expected_coverage="lower_miss" if 123<outcome["lowerRaw"] else "upper_miss" if 123>outcome["upperRaw"] else "covered"
        self.assertEqual(outcome["coverageOutcome"],expected_coverage)
        self.assertEqual(summary["evaluatedForecastCount"],1);self.assertEqual(summary["cumulativeMAE"],outcome["absoluteError"])
        self.assertFalse(commit["latestForecastPointerModified"]);self.assertEqual(pointer["outcomeId"],job["outcomeId"])
        after={str(p.relative_to(self.forecast_root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in self.forecast_root.rglob("*") if p.is_file()}
        self.assertEqual(self.before,after)
        pointer_bytes=(self.runtime/"deployments/dhaka_south/monitoring/latest.json").read_bytes()
        recovered=execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(path),staging=str(self.runtime/"outcome-staging"/job["outcomeId"])))
        self.assertTrue(recovered["recovered"]);self.assertEqual(pointer_bytes,(self.runtime/"deployments/dhaka_south/monitoring/latest.json").read_bytes())

    def test_02_duplicate_forecast_and_correction_are_rejected(self):
        correction,correction_path=build_outcome_job(self.runtime,self.forecast_job,record_id="observation-1",observed=124)
        with self.assertRaises(ForecastOutcomeCommitError) as corrected:execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(correction_path),staging=str(self.runtime/"outcome-staging"/correction["outcomeId"])))
        self.assertEqual(corrected.exception.code,"correction_workflow_not_governed")
        job,path=build_outcome_job(self.runtime,self.forecast_job,record_id="observation-2")
        with self.assertRaises(ForecastOutcomeCommitError) as caught:execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(path),staging=str(self.runtime/"outcome-staging"/job["outcomeId"])))
        self.assertEqual(caught.exception.code,"duplicate_forecast_outcome")

    def test_observation_payload_hash_mismatch_rejected(self):
        job,path=build_outcome_job(self.runtime,self.forecast_job,record_id="hash-failure")
        value=json.loads(path.read_text());value["observationPayloadSha256"]="0"*64;path.write_text(json.dumps(value))
        with self.assertRaises(ForecastOutcomeCommitError) as caught:execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(path),staging=str(self.runtime/"outcome-staging"/job["outcomeId"])))
        self.assertEqual(caught.exception.code,"observation_integrity_error")

    def test_identity_source_and_recording_time_mismatches_fail_closed(self):
        cases=(("deploymentId","other","deployment_mismatch"),("targetColumn","other","targetColumn_mismatch"),("forecastHorizonWeeks",3,"forecastHorizonWeeks_mismatch"),("forecastTargetPeriod","2023-W01","forecastTargetPeriod_mismatch"),("observationSourceType","other","observationSourceType_mismatch"),("observationSourceId","other","observationSourceId_mismatch"),("observationRecordedAt","2020-01-01T00:00:00Z","observation_before_completion"))
        for field,value,code in cases:
            with self.subTest(field=field):
                job,path=build_outcome_job(self.runtime,self.forecast_job,record_id=f"mismatch-{field}")
                record=json.loads(path.read_text());record["observation"][field]=value;record["observationPayloadSha256"]=canonical_sha(record["observation"]);path.write_text(json.dumps(record))
                with self.assertRaises((ForecastOutcomeCommitError,ValueError)) as caught:execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(path),staging=str(self.runtime/"outcome-staging"/job["outcomeId"])))
                if isinstance(caught.exception,ForecastOutcomeCommitError):self.assertEqual(caught.exception.code,code)

    def test_expected_forecast_commit_mismatch_and_tamper_rejected(self):
        job,path=build_outcome_job(self.runtime,self.forecast_job,record_id="commit-mismatch")
        record=json.loads(path.read_text());record["expectedForecastCommitSha256"]="0"*64;path.write_text(json.dumps(record))
        with self.assertRaises(ForecastOutcomeCommitError) as caught:execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(path),staging=str(self.runtime/"outcome-staging"/job["outcomeId"])))
        self.assertEqual(caught.exception.code,"forecast_commit_mismatch")

    def test_pending_empirical_range_is_not_evaluable(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime,workspace,forecast_path,forecast_job=build_ready_runtime(Path(directory),row_count=111)
            execute_forecast(SimpleNamespace(runtime_root=str(runtime),job_record=str(forecast_path),workspace=str(workspace),staging=str(runtime/"staging"/forecast_job["runId"])))
            job,path=build_outcome_job(runtime,forecast_job,record_id="pending-range")
            execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(path),staging=str(runtime/"outcome-staging"/job["outcomeId"])))
            outcome=json.loads((runtime/"forecast-outcomes"/job["outcomeId"]/"artifacts/outcome_evaluation.json").read_text())
            self.assertEqual(outcome["coverageOutcome"],"not_evaluable_no_empirical_range")
            self.assertIsNone(outcome["lowerRaw"]);self.assertIsNone(outcome["intervalWidth"])

if __name__=="__main__":unittest.main()
