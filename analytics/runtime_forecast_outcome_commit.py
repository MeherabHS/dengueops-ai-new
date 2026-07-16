"""Validate and atomically commit immutable P1.4G forecast-outcome evidence."""
from __future__ import annotations
import hashlib, json, math, os, shutil, time
from pathlib import Path
from typing import Any, Mapping
from jsonschema import Draft202012Validator, FormatChecker
from forecast_outcome_metrics import aggregate_outcomes, calculate_period_completion, deterministic_outcome_set_hash, deterministic_outcome_sort, evaluate_outcome
from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within

POLICY_ID="RUNTIME.FORECAST_OUTCOME.MONITORING"; POLICY_VERSION="p1.4g-v1"
SCHEMAS={"observation.json":"runtime_forecast_observation.schema.json","outcome_evaluation.json":"runtime_forecast_outcome.schema.json","monitoring_summary.json":"runtime_monitoring_summary.schema.json"}
class ForecastOutcomeCommitError(RuntimeError):
    def __init__(self,message:str,code:str="outcome_commit_failed",retryable:bool=False): super().__init__(message);self.code=code;self.retryable=retryable

def _json(path:Path)->dict[str,Any]:
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:raise ForecastOutcomeCommitError(f"Invalid outcome JSON: {path.name}.","outcome_integrity_error") from exc
    if not isinstance(value,dict):raise ForecastOutcomeCommitError("Outcome JSON must be an object.","outcome_integrity_error")
    return value

def _validate(path:Path,schema_name:str)->dict[str,Any]:
    value=_json(path);schema=_json(ROOT/"config"/schema_name);errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value),key=lambda e:list(e.path))
    if errors:raise ForecastOutcomeCommitError(f"{path.name} failed schema validation: {errors[0].message}","outcome_schema_error")
    return value

def _lock(path:Path,timeout:float=30)->int:
    path.parent.mkdir(parents=True,exist_ok=True);deadline=time.monotonic()+timeout
    while True:
        try:return os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:
            if time.monotonic()>=deadline:raise ForecastOutcomeCommitError("Monitoring commit lock timed out.","monitoring_locked",True)
            time.sleep(.1)

def _replace(source:Path,target:Path)->None:
    for attempt in range(6):
        try:os.replace(source,target);return
        except PermissionError:
            if attempt==5:raise
            time.sleep(.05*(2**attempt))

def _schema_validate_value(value:dict[str,Any],name:str)->None:
    schema=_json(ROOT/"config"/name);errors=list(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value))
    if errors:raise ForecastOutcomeCommitError(f"Generated value failed {name}: {errors[0].message}","outcome_schema_error")

def _observation_signature(value:Mapping[str,Any])->str:
    keys=("deploymentId","geography","targetColumn","forecastHorizonWeeks","forecastTargetPeriod","observedRaw","observationSourceType","observationSourceId","observationRecordId","observationRecordedAt")
    payload={k:value[k] for k in keys}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()

def _validate_outcome_arithmetic(observation:Mapping[str,Any],outcome:Mapping[str,Any])->None:
    if observation["observedRaw"]!=outcome["observedRaw"] or observation["forecastRunId"]!=outcome["forecastRunId"]:raise ForecastOutcomeCommitError("Observation and outcome binding mismatch.","outcome_integrity_error")
    uncertainty={"uncertaintyStatus":outcome["empiricalRangeStatus"],"lowerRaw":outcome["lowerRaw"],"upperRaw":outcome["upperRaw"]}
    expected=evaluate_outcome(outcome["forecastRaw"],observation["observedRaw"],uncertainty)
    if any(outcome.get(key)!=value for key,value in expected.items()):raise ForecastOutcomeCommitError("Outcome metric arithmetic mismatch.","outcome_metric_mismatch")

def _verified_existing(root:Path)->tuple[dict[str,Any],dict[str,Any],dict[str,Any],str]:
    commit=_validate(root/"metadata/commit.json","runtime_forecast_outcome_commit.schema.json")
    artifacts=root/"artifacts"
    for name,digest in commit["artifactHashes"].items():
        if sha256_file(artifacts/name)!=digest:raise ForecastOutcomeCommitError("Committed outcome artifact changed.","outcome_integrity_error")
    observation=_validate(artifacts/"observation.json",SCHEMAS["observation.json"])
    outcome=_validate(artifacts/"outcome_evaluation.json",SCHEMAS["outcome_evaluation.json"])
    _validate_outcome_arithmetic(observation,outcome)
    return commit,observation,outcome,sha256_file(root/"metadata/commit.json")

def _breakdowns(records:list[dict[str,Any]],key)->list[dict[str,Any]]:
    groups:dict[str,list[dict[str,Any]]]={}
    for record in records:groups.setdefault(key(record),[]).append(record)
    result=[]
    for identity in sorted(groups):
        metrics=aggregate_outcomes(groups[identity]);result.append({"identity":identity,"evaluatedForecastCount":metrics["evaluatedForecastCount"],"cumulativeMAE":metrics["cumulativeMAE"],"cumulativeRMSE":metrics["cumulativeRMSE"],"cumulativeBias":metrics["cumulativeBias"]})
    return result

def _eligible_forecasts(runtime_root:Path,as_of:str,policy:Mapping[str,Any])->int:
    instant=__import__("datetime").datetime.fromisoformat(as_of.replace("Z","+00:00"));count=0
    for run_root in sorted((runtime_root/"runs").glob("*")):
        try:
            commit=_validate(run_root/"metadata/commit.json","runtime_commit.schema.json");forecast=_validate(run_root/"artifacts/forecast_output.json","runtime_forecast_output.schema.json")
            scope=policy["forecast_scope"]
            if commit.get("status")!="committed" or commit.get("workflowMode")!="quick_forecast" or (forecast.get("policy",{}).get("id"),forecast.get("policy",{}).get("version"),forecast.get("policy",{}).get("sha256"))!=(scope["required_policy_id"],scope["required_policy_version"],scope["required_policy_sha256"]):continue
            hashes=commit.get("artifactHashes",{})
            if not hashes or any(not (run_root/"artifacts"/name).is_file() or sha256_file(run_root/"artifacts"/name)!=digest for name,digest in hashes.items()):continue
            if forecast.get("deploymentId")!="dhaka_south" or forecast.get("target")!="target_cases_next_2w" or forecast.get("horizonWeeks")!=2:continue
            manifest=_json(run_root/"artifacts/input_manifest.json");validation_path=run_root/"metadata/validation.json";validation=_json(validation_path)
            if sha256_file(validation_path)!=manifest.get("validationRecordSha256") or validation.get("datasetIdentity",{}).get("geography")!={"geography_level":"city","geography_id":"BGD-DHAKA-SOUTH","geography_name":"Dhaka South"}:continue
            if instant>=calculate_period_completion(forecast["targetPeriod"]):count+=1
        except Exception:continue
    return count

def _publish_pointer(runtime_root:Path,committed:Path,commit:dict[str,Any],policy:dict[str,Any],published_at:str)->dict[str,Any]:
    summary=committed/"artifacts/monitoring_summary.json";commit_path=committed/"metadata/commit.json"
    pointer={"schemaVersion":"1.0","deploymentId":commit["deploymentId"],"outcomeId":commit["outcomeId"],
      "outcomeCommitPath":f"forecast-outcomes/{commit['outcomeId']}/metadata/commit.json","outcomeCommitSha256":sha256_file(commit_path),
      "monitoringSummaryPath":f"forecast-outcomes/{commit['outcomeId']}/artifacts/monitoring_summary.json","monitoringSummarySha256":sha256_file(summary),
      "publishedAt":published_at,"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy["policy_sha256"]}
    _schema_validate_value(pointer,"runtime_monitoring_latest.schema.json")
    target=runtime_root/"deployments"/commit["deploymentId"]/"monitoring/latest.json";atomic_json(target,pointer)
    return pointer

def commit_forecast_outcome(runtime_root:Path,staging_path:Path,job:dict[str,Any],policy:dict[str,Any],forecast_snapshot:dict[str,str])->dict[str,Any]:
    runtime_root=require_absolute_directory(runtime_root,"runtime root");staging=require_within(runtime_root,staging_path,"outcome staging")
    if staging.parent!=(runtime_root/"outcome-staging").resolve() or staging.name!=job["outcomeId"]:raise ForecastOutcomeCommitError("Outcome staging identity mismatch.")
    artifacts=staging/"artifacts";observation=_validate(artifacts/"observation.json",SCHEMAS["observation.json"]);outcome=_validate(artifacts/"outcome_evaluation.json",SCHEMAS["outcome_evaluation.json"])
    identity=(job["outcomeId"],job["jobId"],job["forecastRunId"])
    if tuple(observation.get(k) for k in ("outcomeId","jobId","forecastRunId"))!=identity or tuple(outcome.get(k) for k in ("outcomeId","jobId","forecastRunId"))!=identity:raise ForecastOutcomeCommitError("Outcome identity mismatch.")
    if outcome["observationArtifactSha256"]!=sha256_file(artifacts/"observation.json"):raise ForecastOutcomeCommitError("Observation hash binding mismatch.")
    if outcome["forecastCommitSha256"]!=job["expectedForecastCommitSha256"] or outcome["deploymentId"]!=job["deploymentId"]:raise ForecastOutcomeCommitError("Forecast outcome governance binding mismatch.","outcome_integrity_error")
    _validate_outcome_arithmetic(observation,outcome)
    latest_path=runtime_root/"deployments"/job["deploymentId"]/"latest.json";latest_before=latest_path.read_bytes() if latest_path.exists() else None
    for relative,digest in forecast_snapshot.items():
        path=runtime_root/"runs"/job["forecastRunId"]/relative
        if not path.exists() or sha256_file(path)!=digest:raise ForecastOutcomeCommitError("Original forecast changed during outcome evaluation.","forecast_integrity_error")
    lock_path=runtime_root/"deployments"/job["deploymentId"]/"monitoring/locks/commit.lock";fd=_lock(lock_path)
    try:
        committed_root=runtime_root/"forecast-outcomes"/job["outcomeId"]
        if committed_root.exists():
            commit,committed_observation,committed_outcome,_= _verified_existing(committed_root)
            if commit["jobId"]!=job["jobId"] or commit["forecastRunId"]!=job["forecastRunId"]:raise ForecastOutcomeCommitError("Outcome identity is already used.","duplicate_forecast_outcome")
            if committed_observation["submittedPayloadSha256"]!=observation["submittedPayloadSha256"] or committed_outcome["forecastCommitSha256"]!=outcome["forecastCommitSha256"]:raise ForecastOutcomeCommitError("Outcome retry evidence differs from the immutable commit.","outcome_retry_conflict")
            pointer=_publish_pointer(runtime_root,committed_root,commit,policy,commit["committedAt"])
            if (latest_path.read_bytes() if latest_path.exists() else None)!=latest_before:raise ForecastOutcomeCommitError("Forecast latest pointer changed.","forecast_latest_pointer_changed")
            shutil.rmtree(staging)
            return {"outcomeRoot":str(committed_root),"commit":commit,"pointer":pointer,"recovered":True}
        existing_records=[];included=[]
        for root in sorted((runtime_root/"forecast-outcomes").glob("*")):
            commit,prior_observation,prior,evidence_commit_sha=_verified_existing(root)
            if prior["forecastRunId"]==job["forecastRunId"]:
                code="correction_workflow_not_governed" if prior_observation["observationRecordId"]==observation["observationRecordId"] and _observation_signature(prior_observation)!=_observation_signature(observation) else "duplicate_forecast_outcome"
                raise ForecastOutcomeCommitError("The forecast already has committed outcome evidence.",code)
            if prior_observation["observationRecordId"]==observation["observationRecordId"] and _observation_signature(prior_observation)!=_observation_signature(observation):raise ForecastOutcomeCommitError("Observation record identity conflicts with committed evidence.","conflicting_observation_record")
            prior["outcomeEvidenceSha256"]=commit["artifactHashes"]["outcome_evaluation.json"];existing_records.append(prior);included.append({"outcomeId":prior["outcomeId"],"outcomeEvidenceSha256":prior["outcomeEvidenceSha256"]})
        new_sha=sha256_file(artifacts/"outcome_evaluation.json");outcome["outcomeEvidenceSha256"]=new_sha;records=deterministic_outcome_sort([*existing_records,outcome]);included.append({"outcomeId":outcome["outcomeId"],"outcomeEvidenceSha256":new_sha})
        aggregate=aggregate_outcomes(records);eligible=_eligible_forecasts(runtime_root,outcome["evaluatedAt"],policy)
        if eligible<len(records):raise ForecastOutcomeCommitError("Evaluated outcomes exceed eligible forecasts.","monitoring_count_error")
        summary={"schemaVersion":"1.0","deploymentId":job["deploymentId"],"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy["policy_sha256"],"generatedAt":outcome["evaluatedAt"],"eligibilityAsOf":outcome["evaluatedAt"],**aggregate,
          "totalEligibleForecastCount":eligible,"pendingOutcomeCount":eligible-len(records),
          "modelBreakdowns":_breakdowns(records,lambda r:f"{r['modelId']}|{r['modelFamily']}|{r['modelParametersSha256']}"),
          "forecastPolicyBreakdowns":_breakdowns(records,lambda r:f"{r['forecastPolicyId']}|{r['forecastPolicyVersion']}|{r['forecastPolicySha256']}"),
          "uncertaintyStatusBreakdowns":_breakdowns(records,lambda r:r["empiricalRangeStatus"]),
          "includedOutcomes":sorted(included,key=lambda x:x["outcomeId"]),"outcomeSetSha256":deterministic_outcome_set_hash(records),
          "limitations":["Synthetic benchmark outcome monitoring only; not operational surveillance.","Observed outcomes do not retrain, promote, or replace any model.","Empirical range coverage is historical evidence and not prediction-interval coverage."]}
        atomic_json(artifacts/"monitoring_summary.json",summary);_validate(artifacts/"monitoring_summary.json",SCHEMAS["monitoring_summary.json"])
        hashes={name:sha256_file(artifacts/name) for name in SCHEMAS}
        committed_at=outcome["evaluatedAt"];commit={"schemaVersion":"1.0","outcomeId":job["outcomeId"],"jobId":job["jobId"],"forecastRunId":job["forecastRunId"],"observationRecordId":observation["observationRecordId"],"deploymentId":job["deploymentId"],"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy["policy_sha256"],"forecastCommitSha256":job["expectedForecastCommitSha256"],"status":"committed","artifactHashes":hashes,"latestForecastPointerModified":False,"committedAt":committed_at}
        _schema_validate_value(commit,"runtime_forecast_outcome_commit.schema.json");atomic_json(staging/"metadata/commit.json",commit)
        (runtime_root/"forecast-outcomes").mkdir(parents=True,exist_ok=True);_replace(staging,committed_root)
        pointer=_publish_pointer(runtime_root,committed_root,commit,policy,committed_at)
        _verified_existing(committed_root)
        if (latest_path.read_bytes() if latest_path.exists() else None)!=latest_before:raise ForecastOutcomeCommitError("Forecast latest pointer changed.","forecast_latest_pointer_changed")
        return {"outcomeRoot":str(committed_root),"commit":commit,"pointer":pointer,"recovered":False}
    finally:
        os.close(fd);lock_path.unlink(missing_ok=True)
