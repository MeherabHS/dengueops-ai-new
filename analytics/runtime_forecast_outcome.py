"""Isolated P1.4G forecast-outcome evaluation worker entry point."""
from __future__ import annotations
import argparse, hashlib, json, math, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker
from forecast_outcome_metrics import calculate_period_completion, evaluate_outcome, parse_target_period
from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_forecast_outcome_commit import ForecastOutcomeCommitError, commit_forecast_outcome
from runtime_forecast_outcome_policy import load_and_validate_forecast_outcome_policy

def _now()->str:return datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
def _json(path:Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict):raise ValueError(f"{path.name} must be an object.")
    return value
def _schema(value:dict[str,Any],name:str)->None:
    schema=_json(ROOT/"config"/name);errors=list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value))
    if errors:raise ValueError(f"{name}: {errors[0].message}")
def _update_job(path:Path,job:dict[str,Any],progress:str)->None:
    job.update(progress=progress,updatedAt=_now());atomic_json(path,job)

def _verified_forecast(root:Path,run_id:str,expected_commit:str,policy:dict[str,Any])->tuple[dict[str,Any],dict[str,str]]:
    run=root/"runs"/run_id
    if not run.is_dir():raise ForecastOutcomeCommitError("Committed forecast not found.","forecast_not_found")
    snapshot={str(p.relative_to(run)).replace("\\","/"):sha256_file(p) for p in sorted(run.rglob("*")) if p.is_file()}
    commit_path=run/"metadata/commit.json"
    if snapshot.get("metadata/commit.json")!=expected_commit:raise ForecastOutcomeCommitError("Forecast commit identity mismatch.","forecast_commit_mismatch")
    commit=_json(commit_path);_schema(commit,"runtime_commit.schema.json")
    if commit.get("workflowMode")!="quick_forecast" or commit.get("status")!="committed":raise ForecastOutcomeCommitError("Forecast workflow is not eligible.","forecast_not_eligible")
    for name,digest in commit["artifactHashes"].items():
        if snapshot.get(f"artifacts/{name}")!=digest:raise ForecastOutcomeCommitError("Committed forecast artifact hash mismatch.","forecast_integrity_error")
    forecast=_json(run/"artifacts/forecast_output.json");uncertainty=_json(run/"artifacts/forecast_uncertainty.json");calibration=_json(run/"artifacts/forecast_calibration.json");card=_json(run/"artifacts/model_card.json")
    for value,name in ((forecast,"runtime_forecast_output.schema.json"),(uncertainty,"runtime_forecast_uncertainty.schema.json"),(calibration,"runtime_forecast_calibration.schema.json"),(card,"runtime_model_card.schema.json")):_schema(value,name)
    manifest=_json(run/"artifacts/input_manifest.json");validation_path=run/"metadata/validation.json";validation=_json(validation_path)
    if sha256_file(validation_path)!=manifest.get("validationRecordSha256"):raise ForecastOutcomeCommitError("Forecast validation evidence hash mismatch.","forecast_integrity_error")
    scope=policy["forecast_scope"]
    expected=(run_id,commit["datasetId"],commit["deploymentId"])
    if (forecast.get("runId"),forecast.get("datasetId"),forecast.get("deploymentId"))!=expected:raise ForecastOutcomeCommitError("Forecast identity mismatch.","forecast_integrity_error")
    checks=[(forecast.get("policy",{}).get("id"),scope["required_policy_id"]),(forecast.get("policy",{}).get("version"),scope["required_policy_version"]),(forecast.get("policy",{}).get("sha256"),scope["required_policy_sha256"]),(forecast.get("target"),scope["target_column"]),(forecast.get("horizonWeeks"),scope["forecast_horizon_weeks"]),(forecast.get("activeModelId"),scope["model_id"]),(forecast.get("modelFamily"),scope["model_family"]),(forecast.get("parameterHash"),scope["model_parameters_sha256"]),(forecast.get("candidateRegistrySha256"),scope["candidate_registry_sha256"]),(forecast.get("trainingDataIdentity",{}).get("featureOrderSha256"),scope["feature_order_sha256"])]
    if any(a!=b for a,b in checks):raise ForecastOutcomeCommitError("Forecast governance identity mismatch.","forecast_not_eligible")
    if validation.get("datasetIdentity",{}).get("geography")!={"geography_level":"city","geography_id":"BGD-DHAKA-SOUTH","geography_name":"Dhaka South"}:raise ForecastOutcomeCommitError("Forecast geography evidence mismatch.","forecast_not_eligible")
    if uncertainty.get("runId")!=run_id or calibration.get("runId")!=run_id or uncertainty.get("residualSourceArtifactSha256") not in (None,snapshot["artifacts/forecast_calibration.json"]):raise ForecastOutcomeCommitError("Forecast uncertainty evidence mismatch.","forecast_integrity_error")
    origin=validation.get("acceptedPeriod",{}).get("end");oy,ow=parse_target_period(origin);monday=datetime.fromisocalendar(oy,ow,1)+timedelta(weeks=2);ty,tw,_=monday.isocalendar();target=f"{ty}-W{tw:02d}"
    if tw==53 or target!=forecast.get("targetPeriod"):raise ForecastOutcomeCommitError("Forecast origin and target period do not reconcile.","target_period_mismatch")
    return {"commit":commit,"forecast":forecast,"uncertainty":uncertainty,"calibration":calibration,"card":card,"validation":validation,"origin":origin,"snapshot":snapshot},snapshot

def execute(args:argparse.Namespace)->dict[str,Any]:
    root=require_absolute_directory(args.runtime_root,"runtime root");job_path=require_within(root,args.job_record,"job record");staging=require_within(root,args.staging,"outcome staging");job=_json(job_path)
    _schema(job,"runtime_job.schema.json")
    if job.get("jobKind")!="forecast_outcome":raise ValueError("Not a forecast outcome job.")
    policy,digest=load_and_validate_forecast_outcome_policy(job["deploymentId"])
    if (job["policyId"],job["policyVersion"],job["policySha256"])!=(policy["policy_id"],policy["policy_version"],digest):raise ForecastOutcomeCommitError("Outcome policy identity mismatch.","outcome_policy_mismatch")
    _update_job(job_path,job,"validating_forecast_commit");bundle,snapshot=_verified_forecast(root,job["forecastRunId"],job["expectedForecastCommitSha256"],policy)
    submitted=job["observation"];_update_job(job_path,job,"validating_observation")
    submitted_sha=hashlib.sha256(json.dumps(submitted,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    if submitted_sha!=job["observationPayloadSha256"]:raise ForecastOutcomeCommitError("Observation payload hash mismatch.","observation_integrity_error")
    if submitted["deploymentId"]!=bundle["forecast"]["deploymentId"]:raise ForecastOutcomeCommitError("Observation deployment mismatch.","deployment_mismatch")
    geography={"level":bundle["validation"]["datasetIdentity"]["geography"]["geography_level"],"id":bundle["validation"]["datasetIdentity"]["geography"]["geography_id"],"name":bundle["validation"]["datasetIdentity"]["geography"]["geography_name"]}
    for field,expected in (("geography",geography),("targetColumn",bundle["forecast"]["target"]),("forecastHorizonWeeks",bundle["forecast"]["horizonWeeks"]),("forecastTargetPeriod",bundle["forecast"]["targetPeriod"]),("observationSourceType",policy["observation_scope"]["source_type"]),("observationSourceId",policy["observation_scope"]["source_id"])):
        if submitted[field]!=expected:raise ForecastOutcomeCommitError(f"Observation {field} mismatch.",f"{field}_mismatch")
    completion=calculate_period_completion(submitted["forecastTargetPeriod"],policy["timezone"]);evaluated=datetime.now(timezone.utc);recorded=datetime.fromisoformat(submitted["observationRecordedAt"].replace("Z","+00:00"))
    if evaluated<completion:raise ForecastOutcomeCommitError("Target period is not complete.","early_outcome_evaluation")
    if recorded<completion:raise ForecastOutcomeCommitError("Observation predates target completion.","observation_before_completion")
    if recorded>evaluated:raise ForecastOutcomeCommitError("Observation timestamp is in the future.","observation_time_invalid")
    evaluated_at=evaluated.isoformat().replace("+00:00","Z");observation={"schemaVersion":"1.0","outcomeId":job["outcomeId"],"jobId":job["jobId"],"forecastRunId":job["forecastRunId"],**submitted,"operatorType":"trusted_internal_unverified","operatorIdentifier":job["operatorIdentifier"],"submittedAt":job["createdAt"],"submittedPayloadSha256":job["observationPayloadSha256"]}
    (staging/"artifacts").mkdir(parents=True,exist_ok=False);(staging/"metadata").mkdir(parents=True,exist_ok=False);atomic_json(staging/"artifacts/observation.json",observation);_schema(observation,"runtime_forecast_observation.schema.json")
    _update_job(job_path,job,"evaluating_forecast_outcome");metrics=evaluate_outcome(bundle["forecast"]["forecastRaw"],submitted["observedRaw"],bundle["uncertainty"]);artifacts=bundle["commit"]["artifactHashes"]
    outcome={"schemaVersion":"1.0","outcomeId":job["outcomeId"],"jobId":job["jobId"],"forecastRunId":job["forecastRunId"],"forecastCommitPath":f"runs/{job['forecastRunId']}/metadata/commit.json","forecastCommitSha256":job["expectedForecastCommitSha256"],"forecastOutputPath":"artifacts/forecast_output.json","forecastOutputSha256":artifacts["forecast_output.json"],"forecastUncertaintyPath":"artifacts/forecast_uncertainty.json","forecastUncertaintySha256":artifacts["forecast_uncertainty.json"],"forecastCalibrationPath":"artifacts/forecast_calibration.json","forecastCalibrationSha256":artifacts["forecast_calibration.json"],"modelCardPath":"artifacts/model_card.json","modelCardSha256":artifacts["model_card.json"],"observationArtifactPath":"artifacts/observation.json","observationArtifactSha256":sha256_file(staging/"artifacts/observation.json"),"deploymentId":job["deploymentId"],"datasetId":bundle["forecast"]["datasetId"],"geography":geography,"sourceType":"uploaded","workflowMode":"quick_forecast","modelId":bundle["forecast"]["activeModelId"],"modelFamily":bundle["forecast"]["modelFamily"],"modelParametersSha256":bundle["forecast"]["parameterHash"],"candidateRegistrySha256":bundle["forecast"]["candidateRegistrySha256"],"featureOrderSha256":bundle["forecast"]["trainingDataIdentity"]["featureOrderSha256"],"forecastPolicyId":bundle["forecast"]["policy"]["id"],"forecastPolicyVersion":bundle["forecast"]["policy"]["version"],"forecastPolicySha256":bundle["forecast"]["policy"]["sha256"],"targetColumn":bundle["forecast"]["target"],"forecastHorizonWeeks":bundle["forecast"]["horizonWeeks"],"forecastOriginPeriod":bundle["origin"],"forecastTargetPeriod":bundle["forecast"]["targetPeriod"],"forecastRaw":bundle["forecast"]["forecastRaw"],"forecastReported":bundle["forecast"]["forecastReported"],"observedRaw":submitted["observedRaw"],**metrics,"evaluatedAt":evaluated_at,"limitations":[policy["maturity_statement"],"Outcome evidence does not modify or retrain the committed forecast.","Empirical range coverage is not prediction-interval coverage."]}
    atomic_json(staging/"artifacts/outcome_evaluation.json",outcome);_schema(outcome,"runtime_forecast_outcome.schema.json");_update_job(job_path,job,"rebuilding_monitoring_summary");result=commit_forecast_outcome(root,staging,job,policy,snapshot);return result

def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--runtime-root",required=True);parser.add_argument("--job-record",required=True);parser.add_argument("--staging",required=True);args=parser.parse_args()
    try:execute(args);return 0
    except ForecastOutcomeCommitError as exc:print(f"outcome_failure:{exc.code}:{1 if exc.retryable else 0}",file=sys.stderr);return 2
    except Exception as exc:print(f"outcome_failure:outcome_execution_failed:0:{type(exc).__name__}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
