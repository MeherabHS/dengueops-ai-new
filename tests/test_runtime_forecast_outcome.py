import hashlib
import json
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/"analytics"))
from runtime_forecast_outcome import execute as execute_outcome
from runtime_forecast_outcome_commit import ForecastOutcomeCommitError
from runtime_forecast_outcome_policy import load_and_validate_forecast_outcome_policy
from runtime_forecast_outcome_source import ForecastSourceError, verify_forecast_source
from runtime_commit import atomic_json, sha256_file
from runtime_worker import run_once
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime
from tests.test_runtime_quick_forecast import build_ready_runtime, execute_historical_quick_forecast, iso_now

def canonical_sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def build_outcome_job(runtime:Path,forecast_job:dict,record_id="observation-1",outcome_id=None,observed=123,schema_version="2.0"):
    run=runtime/"runs"/forecast_job["runId"]
    forecast=json.loads((run/"artifacts/forecast_output.json").read_text())
    commit_sha=hashlib.sha256((run/"metadata/commit.json").read_bytes()).hexdigest()
    policy,digest=load_and_validate_forecast_outcome_policy("dhaka_south",schema_version,"p1.4g-v1" if schema_version=="1.0" else "p2-v1")
    observation={"deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"targetColumn":"target_cases_next_2w","forecastHorizonWeeks":2,"forecastTargetPeriod":forecast["targetPeriod"],"observedRaw":observed,"observationSourceType":"synthetic_benchmark","observationSourceId":"dhaka_south_synthetic_benchmark","observationRecordId":record_id,"observationRecordedAt":iso_now(),"limitationsAcknowledged":True}
    job_id=str(uuid.uuid4());outcome_id=outcome_id or str(uuid.uuid4());created=iso_now()
    job={"schemaVersion":policy["schema_version"],"jobKind":"forecast_outcome","jobId":job_id,"outcomeId":outcome_id,"forecastRunId":forecast_job["runId"],"expectedForecastCommitSha256":commit_sha,"observation":observation,"observationPayloadSha256":canonical_sha(observation),"operatorIdentifier":"test-operator","deploymentId":"dhaka_south","workflowMode":"forecast_outcome_monitoring","policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":digest,"status":"running","progress":"validating_forecast_commit","createdAt":created,"claimedAt":created,"startedAt":created,"updatedAt":created,"completedAt":None,"heartbeatAt":created,"workerId":"test","processId":None,"timeoutSeconds":120,"retryCount":0,"error":None,"committedOutcomeId":None}
    path=runtime/"jobs/running"/f"{job_id}.json";path.write_text(json.dumps(job),encoding="utf-8")
    return job,path

def build_p2v2_approved_runtime(base:Path):
    runtime,_workspace,_pending,assessment_job=build_ready_assessment_runtime(base,assessment_policy_version="p2-v2")
    if not run_once(runtime,"p2-v2-outcome-assessment"):raise AssertionError("p2-v2 assessment did not complete")
    assessment=runtime/"assessments"/assessment_job["assessmentId"];summary_path=assessment/"artifacts/assessment_summary.json"
    comparison_path=assessment/"artifacts/candidate_model_comparison.json";summary=json.loads(summary_path.read_text())
    selected=next(value for value in summary["candidates"] if value["modelId"]==summary["technicalWinnerModelId"])
    if not selected["selectionEligible"]:raise AssertionError("technical winner is not eligible")
    policy=json.loads((ROOT/"config/deployments/dhaka_south/decision_policy.json").read_text())
    decision_id,authorization_id,job_id,run_id=[str(uuid.uuid4()) for _ in range(4)]
    created=iso_now();assessment_commit_path=assessment/"metadata/commit.json";assessment_commit_sha=sha256_file(assessment_commit_path)
    decision_root=runtime/"decisions"/decision_id;decision_root.mkdir(parents=True)
    decision={"schemaVersion":"2.0","decisionId":decision_id,"assessmentId":assessment_job["assessmentId"],"assessmentCommitSha256":assessment_commit_sha,
        "assessmentSchemaVersion":"2.0","assessmentSummarySha256":sha256_file(summary_path),"comparisonSha256":sha256_file(comparison_path),
        "recommendationSha256":summary["evidenceHashes"]["recommendationSha256"],"foldPlanSha256":summary["foldPlanSha256"],
        "assessmentLabelledRows":summary["labelledRows"],"assessmentPlannedFoldCount":summary["foldPolicy"]["plannedFoldCount"],
        "selectedEvaluationPeriod":summary["foldPolicy"]["selectedEvaluationPeriod"],"datasetId":summary["datasetId"],"deploymentId":"dhaka_south",
        "validationRecordSha256":summary["provenance"]["validationRecordSha256"],"assessmentPolicyId":policy["allowedAssessmentPolicyId"],
        "assessmentPolicyVersion":policy["allowedAssessmentPolicyVersion"],"assessmentPolicySha256":policy["allowedAssessmentPolicySha256"],
        "decisionPolicyId":policy["policyId"],"decisionPolicyVersion":policy["policyVersion"],"decisionPolicySha256":policy["policySha256"],
        "candidateRegistrySha256":policy["candidateRegistrySha256"],"featureOrderSha256":policy["featureOrderSha256"],
        "technicalWinnerModelId":selected["modelId"],"technicalWinnerParameterSha256":selected["parametersSha256"],
        "decision":"approve_technical_winner","selectionType":"technical_winner","selectedModelId":selected["modelId"],
        "selectedModelFamily":selected["modelFamily"],"selectedModelParameterSha256":selected["parametersSha256"],
        "selectedModelPreprocessingIdentity":selected["preprocessingIdentity"],"selectedCandidateStatus":"technical_winner",
        "decisionScope":"one_run","operatorType":"trusted_internal_unverified","operatorIdentifier":"test-operator","institutionalApproval":False,
        "reason":"Governed p2-v2 outcome compatibility fixture.","technicalWinnerNotSelectedAcknowledged":False,
        "uncertaintyLimitationsAcknowledged":True,"deploymentModelAdopted":False,"limitationsAcknowledged":True,
        "decisionStatus":"approved_technical_winner","forecastAuthorized":True,"authorizationId":authorization_id,"createdAt":created,
        "correlationId":str(uuid.uuid4()),"supersedesDecisionId":None,"supersessionStatus":"active"}
    atomic_json(decision_root/"decision.json",decision)
    decision_commit={"schemaVersion":"2.0","decisionId":decision_id,"assessmentId":assessment_job["assessmentId"],
        "decisionSha256":sha256_file(decision_root/"decision.json"),"assessmentCommitSha256":assessment_commit_sha,
        "assessmentSchemaVersion":"2.0","assessmentSummarySha256":sha256_file(summary_path),"assessmentPolicyId":policy["allowedAssessmentPolicyId"],
        "assessmentPolicyVersion":policy["allowedAssessmentPolicyVersion"],"assessmentPolicySha256":policy["allowedAssessmentPolicySha256"],
        "decisionPolicyId":policy["policyId"],"decisionPolicyVersion":policy["policyVersion"],"decisionPolicySha256":policy["policySha256"],
        "foldPlanSha256":summary["foldPlanSha256"],"assessmentLabelledRows":summary["labelledRows"],
        "assessmentPlannedFoldCount":summary["foldPolicy"]["plannedFoldCount"],"status":"committed","committedAt":created,
        "latestPointerUpdated":False,"deploymentProfileModified":False}
    atomic_json(decision_root/"commit.json",decision_commit);decision_commit_sha=sha256_file(decision_root/"commit.json")
    authorization_root=runtime/"authorizations"/authorization_id;authorization_root.mkdir(parents=True)
    expires=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat().replace("+00:00","Z")
    authorization={"schemaVersion":"2.0","authorizationId":authorization_id,"decisionId":decision_id,"decisionCommitSha256":decision_commit_sha,
        "assessmentId":assessment_job["assessmentId"],"assessmentCommitSha256":assessment_commit_sha,
        "assessmentPolicyId":policy["allowedAssessmentPolicyId"],"assessmentPolicyVersion":policy["allowedAssessmentPolicyVersion"],
        "assessmentPolicySha256":policy["allowedAssessmentPolicySha256"],"decisionPolicyId":policy["policyId"],
        "decisionPolicyVersion":policy["policyVersion"],"decisionPolicySha256":policy["policySha256"],"datasetId":summary["datasetId"],
        "deploymentId":"dhaka_south","selectedModelId":selected["modelId"],"selectedModelFamily":selected["modelFamily"],
        "selectedModelParameterSha256":selected["parametersSha256"],"selectedModelPreprocessingIdentity":selected["preprocessingIdentity"],
        "candidateRegistrySha256":policy["candidateRegistrySha256"],"featureOrderSha256":policy["featureOrderSha256"],
        "selectionType":"technical_winner","technicalWinnerModelId":selected["modelId"],"technicalWinnerNotSelectedAcknowledged":False,
        "uncertaintyLimitationsAcknowledged":True,"deploymentModelAdopted":False,"assessmentLabelledRows":summary["labelledRows"],
        "assessmentPlannedFoldCount":summary["foldPolicy"]["plannedFoldCount"],"foldPlanSha256":summary["foldPlanSha256"],
        "workflowMode":"approved_assessment_forecast","scope":"one_run","initialStatus":"available","createdAt":created,"expiresAt":expires,
        "policyId":policy["policyId"],"policyVersion":policy["policyVersion"],"policySha256":policy["policySha256"]}
    atomic_json(authorization_root/"authorization.json",authorization)
    atomic_json(authorization_root/"commit.json",{"schemaVersion":"1.0","authorizationId":authorization_id,"decisionId":decision_id,
        "authorizationSha256":sha256_file(authorization_root/"authorization.json"),"decisionCommitSha256":decision_commit_sha,
        "status":"committed","committedAt":created})
    state=runtime/"authorization-state"/authorization_id;state.mkdir(parents=True)
    atomic_json(state/"reservation.json",{"schemaVersion":"1.0","authorizationId":authorization_id,"decisionId":decision_id,
        "eventType":"reserved","eventId":str(uuid.uuid4()),"createdAt":created,"jobId":job_id,"runId":run_id})
    job={"schemaVersion":"1.0","jobKind":"approved_forecast","jobId":job_id,"runId":run_id,"decisionId":decision_id,
        "decisionCommitSha256":decision_commit_sha,"authorizationId":authorization_id,"assessmentId":assessment_job["assessmentId"],
        "assessmentCommitSha256":assessment_commit_sha,"workspaceId":assessment_job["assessmentId"],"datasetId":summary["datasetId"],
        "deploymentId":"dhaka_south","selectedModelId":selected["modelId"],"selectedModelParameterSha256":selected["parametersSha256"],
        "workflowMode":"approved_assessment_forecast","validationRecordSha256":summary["provenance"]["validationRecordSha256"],
        "status":"queued","progress":"queued","createdAt":created,"claimedAt":None,"startedAt":None,"updatedAt":created,
        "completedAt":None,"heartbeatAt":None,"workerId":None,"processId":None,"timeoutSeconds":600,"retryCount":0,
        "error":None,"committedRunId":None}
    atomic_json(runtime/"jobs/pending"/f"{job_id}.json",job)
    if not run_once(runtime,"p2-v2-outcome-forecast"):raise AssertionError("p2-v2 approved forecast did not complete")
    return runtime,job,selected

class RuntimeForecastOutcomeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.runtime,cls.workspace,cls.forecast_job_path,cls.forecast_job=build_ready_runtime(Path(cls.temp.name))
        execute_historical_quick_forecast(cls.runtime, cls.workspace, cls.forecast_job_path, cls.forecast_job)
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
        existing_root=next((self.runtime/"forecast-outcomes").iterdir());existing_observation=json.loads((existing_root/"artifacts/observation.json").read_text())
        identical,identical_path=build_outcome_job(self.runtime,self.forecast_job,record_id="observation-1")
        for key in identical["observation"]:identical["observation"][key]=existing_observation[key]
        identical["observationPayloadSha256"]=canonical_sha(identical["observation"]);identical_path.write_text(json.dumps(identical))
        recovered=execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(identical_path),staging=str(self.runtime/"outcome-staging"/identical["outcomeId"])))
        self.assertTrue(recovered["recovered"]);self.assertEqual(Path(recovered["outcomeRoot"]),existing_root)
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
        monitoring=(self.runtime/"deployments/dhaka_south/monitoring/latest.json").read_bytes();forecast=(self.runtime/"deployments/dhaka_south/latest.json").read_bytes()
        job,path=build_outcome_job(self.runtime,self.forecast_job,record_id="commit-mismatch")
        record=json.loads(path.read_text());record["expectedForecastCommitSha256"]="0"*64;path.write_text(json.dumps(record))
        with self.assertRaises(ForecastOutcomeCommitError) as caught:execute_outcome(SimpleNamespace(runtime_root=str(self.runtime),job_record=str(path),staging=str(self.runtime/"outcome-staging"/job["outcomeId"])))
        self.assertEqual(caught.exception.code,"forecast_commit_mismatch")
        self.assertEqual(monitoring,(self.runtime/"deployments/dhaka_south/monitoring/latest.json").read_bytes());self.assertEqual(forecast,(self.runtime/"deployments/dhaka_south/latest.json").read_bytes())

    def test_pending_empirical_range_is_not_evaluable(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime,workspace,forecast_path,forecast_job=build_ready_runtime(Path(directory),row_count=111)
            execute_historical_quick_forecast(runtime, workspace, forecast_path, forecast_job)
            job,path=build_outcome_job(runtime,forecast_job,record_id="pending-range")
            execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(path),staging=str(runtime/"outcome-staging"/job["outcomeId"])))
            outcome=json.loads((runtime/"forecast-outcomes"/job["outcomeId"]/"artifacts/outcome_evaluation.json").read_text())
            self.assertEqual(outcome["coverageOutcome"],"not_evaluable_no_empirical_range")
            self.assertIsNone(outcome["lowerRaw"]);self.assertIsNone(outcome["intervalWidth"])

    def test_archived_phase_one_quick_outcome_remains_schema_one(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime,workspace,forecast_path,forecast_job=build_ready_runtime(Path(directory))
            execute_historical_quick_forecast(runtime, workspace, forecast_path, forecast_job)
            job,path=build_outcome_job(runtime,forecast_job,record_id="historical-p1",schema_version="1.0")
            execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(path),staging=str(runtime/"outcome-staging"/job["outcomeId"])))
            root=runtime/"forecast-outcomes"/job["outcomeId"]
            outcome=json.loads((root/"artifacts/outcome_evaluation.json").read_text());commit=json.loads((root/"metadata/commit.json").read_text())
            self.assertEqual((outcome["schemaVersion"],commit["schemaVersion"],commit["policyVersion"]),("1.0","1.0","p1.4g-v1"))

    def test_p2v2_approved_outcome_uses_current_registry_and_normalized_uncertainty(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime,forecast_job,selected=build_p2v2_approved_runtime(Path(directory))
            run=runtime/"runs"/forecast_job["runId"];commit_path=run/"metadata/commit.json"
            commit_sha=sha256_file(commit_path)
            bundle=verify_forecast_source(runtime,forecast_job["runId"],commit_sha,{"approved_forecast_p2"})
            self.assertEqual((bundle["sourceContractVersion"],bundle["modelId"],bundle["modelFamily"]),
                ("p2-v2",selected["modelId"],selected["modelFamily"]))
            job,path=build_outcome_job(runtime,forecast_job,record_id="approved-p2-v2")
            execute_outcome(SimpleNamespace(runtime_root=str(runtime),job_record=str(path),staging=str(runtime/"outcome-staging"/job["outcomeId"])))
            outcome=json.loads((runtime/"forecast-outcomes"/job["outcomeId"]/"artifacts/outcome_evaluation.json").read_text())
            summary=json.loads((runtime/"forecast-outcomes"/job["outcomeId"]/"artifacts/monitoring_summary.json").read_text())
            self.assertEqual(outcome["sourceFamily"],"approved_forecast_p2")
            self.assertEqual(outcome["sourcePolicy"]["policyVersion"],"p2-v2")
            self.assertEqual(outcome["candidateRegistrySha256"],"74cb3635c5e211874ee5ad23196fc95bfdfbdb5c6438cc3d060f0b9ff49acfa0")
            self.assertEqual(outcome["empiricalRangeStatus"],"pending_selected_model_calibration")
            self.assertEqual(outcome["coverageOutcome"],"not_evaluable_no_empirical_range")
            self.assertEqual(summary["latestSourceEvidence"]["modelId"],selected["modelId"])
            self.assertEqual(summary["uncertaintyStatusBreakdowns"][0]["identity"],"pending_selected_model_calibration")

            forecast_path=run/"artifacts/forecast_output.json";original_forecast=forecast_path.read_bytes();original_commit=commit_path.read_bytes()
            for field,value in (("selectedModelFamily","UnsupportedFamily"),("candidateRegistrySha256","0"*64)):
                with self.subTest(tamper=field):
                    forecast=json.loads(original_forecast);forecast[field]=value;atomic_json(forecast_path,forecast)
                    commit=json.loads(original_commit);commit["artifactHashes"]["forecast_output.json"]=sha256_file(forecast_path)
                    atomic_json(commit_path,commit)
                    with self.assertRaises(ForecastSourceError):
                        verify_forecast_source(runtime,forecast_job["runId"],sha256_file(commit_path),{"approved_forecast_p2"})
                    forecast_path.write_bytes(original_forecast);commit_path.write_bytes(original_commit)

            uncertainty_path=run/"artifacts/forecast_uncertainty.json";original_uncertainty=uncertainty_path.read_bytes()
            uncertainty=json.loads(original_uncertainty);uncertainty["uncertaintyReasonCode"]="unexpected";atomic_json(uncertainty_path,uncertainty)
            commit=json.loads(original_commit);commit["artifactHashes"]["forecast_uncertainty.json"]=sha256_file(uncertainty_path);atomic_json(commit_path,commit)
            with self.assertRaises(ForecastSourceError):
                verify_forecast_source(runtime,forecast_job["runId"],sha256_file(commit_path),{"approved_forecast_p2"})
            uncertainty_path.write_bytes(original_uncertainty);commit_path.write_bytes(original_commit)

            commit=json.loads(original_commit)
            commit["assessmentPolicy"]={"policyId":"RUNTIME.DATASET_ASSESSMENT.GOVERNANCE","policyVersion":"p2-v1","policySha256":"04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff"}
            atomic_json(commit_path,commit)
            with self.assertRaises(ForecastSourceError):
                verify_forecast_source(runtime,forecast_job["runId"],sha256_file(commit_path),{"approved_forecast_p2"})

if __name__=="__main__":unittest.main()
