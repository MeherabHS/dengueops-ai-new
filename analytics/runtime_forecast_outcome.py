"""Isolated lifecycle-aware forecast-outcome evaluation worker entry point."""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker
from forecast_outcome_metrics import calculate_period_completion, evaluate_outcome
from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_forecast_outcome_commit import ForecastOutcomeCommitError, commit_forecast_outcome
from runtime_forecast_outcome_policy import load_and_validate_forecast_outcome_policy
from runtime_forecast_outcome_source import ForecastSourceError, verify_forecast_source

def _now()->str:return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _json(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):raise ValueError(f"{path.name} must be an object.")
    return value
def _schema(value:dict[str,Any],name:str)->None:
    schema=_json(ROOT/"config"/name);errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value),key=lambda e:list(e.path))
    if errors:raise ValueError(f"{name}: {errors[0].message}")
def _update_job(path:Path,job:dict[str,Any],progress:str)->None:job.update(progress=progress,updatedAt=_now());atomic_json(path,job)

def _p2_source_evidence(bundle:dict[str,Any])->dict[str,Any]:
    hashes=bundle["commit"]["artifactHashes"]
    common={"forecastOutputPath":"artifacts/forecast_output.json","forecastOutputSha256":hashes["forecast_output.json"],"forecastUncertaintyPath":"artifacts/forecast_uncertainty.json","forecastUncertaintySha256":hashes["forecast_uncertainty.json"],"modelCardPath":"artifacts/model_card.json","modelCardSha256":hashes["model_card.json"],"sourcePolicy":bundle["sourcePolicy"]}
    if bundle["sourceFamily"]=="quick_forecast_p1":
        return {**common,"forecastCalibrationPath":"artifacts/forecast_calibration.json","forecastCalibrationSha256":hashes["forecast_calibration.json"]}
    lifecycle=bundle["lifecycle"]
    return {**common,"assessmentId":lifecycle["assessmentId"],"assessmentCommitSha256":lifecycle["assessmentCommitSha256"],"assessmentPolicy":lifecycle["assessmentPolicy"],"decisionId":lifecycle["decisionId"],"decisionCommitSha256":lifecycle["decisionCommitSha256"],"decisionPolicy":lifecycle["decisionPolicy"],"authorizationId":lifecycle["authorizationId"],"authorizationCommitSha256":lifecycle["authorizationCommitSha256"],"technicalWinnerModelId":lifecycle["technicalWinnerModelId"],"technicalWinnerParameterSha256":lifecycle["technicalWinnerParameterSha256"],"trainingRowCount":lifecycle["trainingRowCount"],"trainingPeriod":lifecycle["trainingPeriod"],"plannedFoldCount":lifecycle["plannedFoldCount"],"successfulFolds":lifecycle["successfulFolds"],"failedFolds":lifecycle["failedFolds"],"selectedEvaluationPeriod":lifecycle["selectedEvaluationPeriod"],"foldPlanSha256":lifecycle["foldPlanSha256"],"featureMatrixSha256":lifecycle["featureMatrixSha256"]}

def execute(args:argparse.Namespace)->dict[str,Any]:
    root=require_absolute_directory(args.runtime_root,"runtime root");job_path=require_within(root,args.job_record,"job record");staging=require_within(root,args.staging,"outcome staging");job=_json(job_path)
    _schema(job,"runtime_job.schema.json")
    if job.get("jobKind")!="forecast_outcome":raise ValueError("Not a forecast outcome job.")
    policy,digest=load_and_validate_forecast_outcome_policy(job["deploymentId"],job["schemaVersion"],job["policyVersion"],job["policySha256"])
    if (job["policyId"],job["policyVersion"],job["policySha256"])!=(policy["policy_id"],policy["policy_version"],digest):raise ForecastOutcomeCommitError("Outcome policy identity mismatch.","outcome_policy_mismatch")
    _update_job(job_path,job,"validating_forecast_commit")
    try:bundle=verify_forecast_source(root,job["forecastRunId"],job["expectedForecastCommitSha256"],{"quick_forecast_p1"} if job["schemaVersion"]=="1.0" else set(policy["source_families"]))
    except ForecastSourceError as exc:raise ForecastOutcomeCommitError(str(exc),exc.code) from exc
    submitted=job["observation"];_update_job(job_path,job,"validating_observation")
    submitted_sha=hashlib.sha256(json.dumps(submitted,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if submitted_sha!=job["observationPayloadSha256"]:raise ForecastOutcomeCommitError("Observation payload hash mismatch.","observation_integrity_error")
    forecast=bundle["forecast"]
    geography={"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"}
    for field,expected in (("deploymentId",forecast["deploymentId"]),("geography",geography),("targetColumn",forecast["target"]),("forecastHorizonWeeks",forecast["horizonWeeks"]),("forecastTargetPeriod",forecast["targetPeriod"]),("observationSourceType",policy["observation_scope"]["source_type"]),("observationSourceId",policy["observation_scope"]["source_id"])):
        if submitted[field]!=expected:raise ForecastOutcomeCommitError(f"Observation {field} mismatch.",f"{field}_mismatch")
    completion=calculate_period_completion(submitted["forecastTargetPeriod"],policy["timezone"]);evaluated=datetime.now(timezone.utc);recorded=datetime.fromisoformat(submitted["observationRecordedAt"].replace("Z","+00:00"))
    if evaluated<completion:raise ForecastOutcomeCommitError("Target period is not complete.","early_outcome_evaluation")
    if recorded<completion:raise ForecastOutcomeCommitError("Observation predates target completion.","observation_before_completion")
    if recorded>evaluated:raise ForecastOutcomeCommitError("Observation timestamp is in the future.","observation_time_invalid")
    evaluated_at=evaluated.isoformat().replace("+00:00","Z");schema_version=job["schemaVersion"]
    observation={"schemaVersion":schema_version,"outcomeId":job["outcomeId"],"jobId":job["jobId"],"forecastRunId":job["forecastRunId"],**submitted,"operatorType":"trusted_internal_unverified","operatorIdentifier":job["operatorIdentifier"],"submittedAt":job["createdAt"],"submittedPayloadSha256":job["observationPayloadSha256"]}
    if schema_version=="2.0":observation.update({"sourceFamily":bundle["sourceFamily"],"monitoringPolicy":{"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":digest}})
    (staging/"artifacts").mkdir(parents=True,exist_ok=False);(staging/"metadata").mkdir(parents=True,exist_ok=False);atomic_json(staging/"artifacts/observation.json",observation);_schema(observation,"runtime_forecast_observation.schema.json")
    _update_job(job_path,job,"evaluating_forecast_outcome");metrics=evaluate_outcome(forecast["forecastRaw"],submitted["observedRaw"],bundle["uncertainty"],schema_version=="2.0")
    if schema_version=="1.0":
        hashes=bundle["commit"]["artifactHashes"]
        outcome={"schemaVersion":"1.0","outcomeId":job["outcomeId"],"jobId":job["jobId"],"forecastRunId":job["forecastRunId"],"forecastCommitPath":f"runs/{job['forecastRunId']}/metadata/commit.json","forecastCommitSha256":job["expectedForecastCommitSha256"],"forecastOutputPath":"artifacts/forecast_output.json","forecastOutputSha256":hashes["forecast_output.json"],"forecastUncertaintyPath":"artifacts/forecast_uncertainty.json","forecastUncertaintySha256":hashes["forecast_uncertainty.json"],"forecastCalibrationPath":"artifacts/forecast_calibration.json","forecastCalibrationSha256":hashes["forecast_calibration.json"],"modelCardPath":"artifacts/model_card.json","modelCardSha256":hashes["model_card.json"],"observationArtifactPath":"artifacts/observation.json","observationArtifactSha256":sha256_file(staging/"artifacts/observation.json"),"deploymentId":job["deploymentId"],"datasetId":forecast["datasetId"],"geography":geography,"sourceType":"uploaded","workflowMode":"quick_forecast","modelId":bundle["modelId"],"modelFamily":bundle["modelFamily"],"modelParametersSha256":bundle["parameterHash"],"candidateRegistrySha256":bundle["candidateRegistrySha256"],"featureOrderSha256":bundle["featureOrderSha256"],"forecastPolicyId":bundle["sourcePolicy"]["policyId"],"forecastPolicyVersion":bundle["sourcePolicy"]["policyVersion"],"forecastPolicySha256":bundle["sourcePolicy"]["policySha256"],"targetColumn":forecast["target"],"forecastHorizonWeeks":forecast["horizonWeeks"],"forecastOriginPeriod":bundle["origin"],"forecastTargetPeriod":forecast["targetPeriod"],"forecastRaw":forecast["forecastRaw"],"forecastReported":forecast["forecastReported"],"observedRaw":submitted["observedRaw"],**metrics,"evaluatedAt":evaluated_at,"limitations":[policy["maturity_statement"],"Outcome evidence does not modify or retrain the committed forecast.","Empirical range coverage is not prediction-interval coverage."]}
    else:
        outcome={"schemaVersion":"2.0","outcomeId":job["outcomeId"],"jobId":job["jobId"],"monitoringPolicy":{"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":digest},"sourceFamily":bundle["sourceFamily"],"sourceForecastRunId":job["forecastRunId"],"sourceForecastCommitPath":f"runs/{job['forecastRunId']}/metadata/commit.json","sourceForecastCommitSha256":job["expectedForecastCommitSha256"],"sourceForecastSchemaVersion":bundle["commit"]["schemaVersion"],"sourceEvidence":_p2_source_evidence(bundle),"observationArtifactPath":"artifacts/observation.json","observationArtifactSha256":sha256_file(staging/"artifacts/observation.json"),"deploymentId":job["deploymentId"],"datasetId":forecast["datasetId"],"geography":geography,"modelId":bundle["modelId"],"modelFamily":bundle["modelFamily"],"modelParametersSha256":bundle["parameterHash"],"candidateRegistrySha256":bundle["candidateRegistrySha256"],"featureOrderSha256":bundle["featureOrderSha256"],"sourcePolicy":bundle["sourcePolicy"],"targetColumn":forecast["target"],"forecastHorizonWeeks":forecast["horizonWeeks"],"forecastOriginPeriod":bundle["origin"],"forecastTargetPeriod":forecast["targetPeriod"],"forecastRaw":forecast["forecastRaw"],"forecastReported":forecast["forecastReported"],"observedRaw":submitted["observedRaw"],"observationSourceType":submitted["observationSourceType"],"observationSourceId":submitted["observationSourceId"],"observationRecordId":submitted["observationRecordId"],**metrics,"evaluatedAt":evaluated_at,"limitations":[policy["maturity_statement"],"Monitoring is evidence-only and does not classify degradation.","Missing empirical-range calibration is not an integrity failure."]}
    atomic_json(staging/"artifacts/outcome_evaluation.json",outcome);_schema(outcome,"runtime_forecast_outcome.schema.json");_update_job(job_path,job,"rebuilding_monitoring_summary")
    return commit_forecast_outcome(root,staging,job,policy,bundle["snapshot"])

def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--runtime-root",required=True);parser.add_argument("--job-record",required=True);parser.add_argument("--staging",required=True);args=parser.parse_args()
    try:execute(args);return 0
    except ForecastOutcomeCommitError as exc:print(f"outcome_failure:{exc.code}:{1 if exc.retryable else 0}",file=sys.stderr);return 2
    except Exception as exc:print(f"outcome_failure:outcome_execution_failed:0:{type(exc).__name__}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
