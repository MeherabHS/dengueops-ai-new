"""Validate and atomically commit immutable forecast-outcome evidence."""
from __future__ import annotations
import hashlib,json,os,shutil,time
from pathlib import Path
from typing import Any,Mapping
from jsonschema import Draft202012Validator,FormatChecker
from forecast_outcome_metrics import aggregate_outcomes,calculate_period_completion,deterministic_outcome_set_hash,deterministic_outcome_sort,evaluate_outcome
from runtime_commit import atomic_json,sha256_file
from runtime_context import ROOT,require_absolute_directory,require_within
from runtime_forecast_outcome_source import ForecastSourceError,verify_forecast_source

SCHEMAS={"observation.json":"runtime_forecast_observation.schema.json","outcome_evaluation.json":"runtime_forecast_outcome.schema.json","monitoring_summary.json":"runtime_monitoring_summary.schema.json"}
class ForecastOutcomeCommitError(RuntimeError):
    def __init__(self,message:str,code:str="outcome_commit_failed",retryable:bool=False):super().__init__(message);self.code=code;self.retryable=retryable
def _json(path:Path)->dict[str,Any]:
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:raise ForecastOutcomeCommitError(f"Invalid outcome JSON: {path.name}.","outcome_integrity_error") from exc
    if not isinstance(value,dict):raise ForecastOutcomeCommitError("Outcome JSON must be an object.","outcome_integrity_error")
    return value
def _schema_value(value:dict[str,Any],name:str)->None:
    schema=_json(ROOT/"config"/name);errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value),key=lambda e:list(e.path))
    if errors:raise ForecastOutcomeCommitError(f"Value failed {name}: {errors[0].message}","outcome_schema_error")
def _validate(path:Path,name:str)->dict[str,Any]:value=_json(path);_schema_value(value,name);return value
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
def _run_id(value:Mapping[str,Any])->str:return str(value.get("forecastRunId",value.get("sourceForecastRunId","")))
def _commit_sha(value:Mapping[str,Any])->str:return str(value.get("forecastCommitSha256",value.get("sourceForecastCommitSha256","")))
def _source_family(value:Mapping[str,Any])->str:return str(value.get("sourceFamily","quick_forecast_p1"))
def _source_policy(value:Mapping[str,Any])->Mapping[str,Any]:
    return value.get("sourcePolicy",{"policyId":value.get("forecastPolicyId"),"policyVersion":value.get("forecastPolicyVersion"),"policySha256":value.get("forecastPolicySha256")})
def _observation_signature(value:Mapping[str,Any])->str:
    keys=("deploymentId","geography","targetColumn","forecastHorizonWeeks","forecastTargetPeriod","observedRaw","observationSourceType","observationSourceId","observationRecordId","observationRecordedAt")
    return hashlib.sha256(json.dumps({k:value[k] for k in keys},sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
def _validate_outcome_arithmetic(observation:Mapping[str,Any],outcome:Mapping[str,Any])->None:
    if observation["observedRaw"]!=outcome["observedRaw"] or observation["forecastRunId"]!=_run_id(outcome):raise ForecastOutcomeCommitError("Observation and outcome binding mismatch.","outcome_integrity_error")
    expected=evaluate_outcome(outcome["forecastRaw"],observation["observedRaw"],{"uncertaintyStatus":outcome["empiricalRangeStatus"],"lowerRaw":outcome["lowerRaw"],"upperRaw":outcome["upperRaw"]},outcome["schemaVersion"]=="2.0")
    if any(outcome.get(k)!=v for k,v in expected.items()):raise ForecastOutcomeCommitError("Outcome metric arithmetic mismatch.","outcome_metric_mismatch")
def _verified_existing(root:Path)->tuple[dict[str,Any],dict[str,Any],dict[str,Any],str]:
    commit=_validate(root/"metadata/commit.json","runtime_forecast_outcome_commit.schema.json");artifacts=root/"artifacts"
    for name,digest in commit["artifactHashes"].items():
        if not (artifacts/name).is_file() or sha256_file(artifacts/name)!=digest:raise ForecastOutcomeCommitError("Committed outcome artifact changed.","outcome_integrity_error")
    observation=_validate(artifacts/"observation.json",SCHEMAS["observation.json"]);outcome=_validate(artifacts/"outcome_evaluation.json",SCHEMAS["outcome_evaluation.json"]);_validate_outcome_arithmetic(observation,outcome)
    if _run_id(outcome)!=commit["forecastRunId"] or _commit_sha(outcome)!=commit["forecastCommitSha256"]:raise ForecastOutcomeCommitError("Committed source binding changed.","outcome_integrity_error")
    return commit,observation,outcome,sha256_file(root/"metadata/commit.json")
def _breakdowns(records:list[dict[str,Any]],key)->list[dict[str,Any]]:
    groups:dict[str,list[dict[str,Any]]]={}
    for record in records:groups.setdefault(key(record),[]).append(record)
    result=[]
    for identity in sorted(groups):
        metrics=aggregate_outcomes(groups[identity]);result.append({"identity":identity,"evaluatedForecastCount":metrics["evaluatedForecastCount"],"cumulativeMAE":metrics["cumulativeMAE"],"cumulativeRMSE":metrics["cumulativeRMSE"],"cumulativeBias":metrics["cumulativeBias"]})
    return result
def _policy_identity(value:Any)->str:
    if not isinstance(value,Mapping):return "not_applicable"
    return f"{value.get('policyId')}|{value.get('policyVersion')}|{value.get('policySha256')}"
def _eligible_runs(runtime_root:Path,as_of:str,allowed:set[str])->set[str]:
    instant=__import__("datetime").datetime.fromisoformat(as_of.replace("Z","+00:00"));eligible=set()
    for run_root in sorted((runtime_root/"runs").glob("*")):
        try:
            commit_path=run_root/"metadata/commit.json";bundle=verify_forecast_source(runtime_root,run_root.name,sha256_file(commit_path),allowed)
            if instant>=calculate_period_completion(bundle["forecast"]["targetPeriod"]):eligible.add(run_root.name)
        except Exception:continue
    return eligible
def _publish_pointer(runtime_root:Path,committed:Path,commit:dict[str,Any],policy:dict[str,Any],published_at:str)->dict[str,Any]:
    summary=committed/"artifacts/monitoring_summary.json";commit_path=committed/"metadata/commit.json";version=commit["schemaVersion"]
    pointer={"schemaVersion":version,"deploymentId":commit["deploymentId"],"outcomeId":commit["outcomeId"],"outcomeCommitPath":f"forecast-outcomes/{commit['outcomeId']}/metadata/commit.json","outcomeCommitSha256":sha256_file(commit_path),"monitoringSummaryPath":f"forecast-outcomes/{commit['outcomeId']}/artifacts/monitoring_summary.json","monitoringSummarySha256":sha256_file(summary),"publishedAt":published_at,"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy["policy_sha256"]}
    _schema_value(pointer,"runtime_monitoring_latest.schema.json");atomic_json(runtime_root/"deployments"/commit["deploymentId"]/"monitoring/latest.json",pointer);return pointer

def commit_forecast_outcome(runtime_root:Path,staging_path:Path,job:dict[str,Any],policy:dict[str,Any],forecast_snapshot:dict[str,str])->dict[str,Any]:
    runtime_root=require_absolute_directory(runtime_root,"runtime root");staging=require_within(runtime_root,staging_path,"outcome staging")
    if staging.parent!=(runtime_root/"outcome-staging").resolve() or staging.name!=job["outcomeId"]:raise ForecastOutcomeCommitError("Outcome staging identity mismatch.")
    artifacts=staging/"artifacts";observation=_validate(artifacts/"observation.json",SCHEMAS["observation.json"]);outcome=_validate(artifacts/"outcome_evaluation.json",SCHEMAS["outcome_evaluation.json"])
    identity=(job["outcomeId"],job["jobId"],job["forecastRunId"])
    if tuple(observation.get(k) for k in ("outcomeId","jobId","forecastRunId"))!=identity or (outcome.get("outcomeId"),outcome.get("jobId"),_run_id(outcome))!=identity:raise ForecastOutcomeCommitError("Outcome identity mismatch.")
    if outcome["observationArtifactSha256"]!=sha256_file(artifacts/"observation.json") or _commit_sha(outcome)!=job["expectedForecastCommitSha256"] or outcome["deploymentId"]!=job["deploymentId"]:raise ForecastOutcomeCommitError("Forecast outcome governance binding mismatch.","outcome_integrity_error")
    _validate_outcome_arithmetic(observation,outcome)
    try:verified=verify_forecast_source(runtime_root,job["forecastRunId"],job["expectedForecastCommitSha256"],{"quick_forecast_p1"} if job["schemaVersion"]=="1.0" else set(policy["source_families"]))
    except ForecastSourceError as exc:raise ForecastOutcomeCommitError(str(exc),exc.code) from exc
    if verified["sourceFamily"]!=_source_family(outcome) or verified["snapshot"]!=forecast_snapshot:raise ForecastOutcomeCommitError("Source family or snapshot changed.","forecast_integrity_error")
    latest_path=runtime_root/"deployments"/job["deploymentId"]/"latest.json";latest_before=latest_path.read_bytes() if latest_path.exists() else None
    monitoring_latest=runtime_root/"deployments"/job["deploymentId"]/"monitoring/latest.json";monitoring_before=monitoring_latest.read_bytes() if monitoring_latest.exists() else None
    lock_path=runtime_root/"deployments"/job["deploymentId"]/"monitoring/locks/commit.lock";fd=_lock(lock_path)
    try:
        committed_root=runtime_root/"forecast-outcomes"/job["outcomeId"]
        if committed_root.exists():
            commit,old_observation,old_outcome,_=_verified_existing(committed_root)
            if commit["jobId"]!=job["jobId"] or commit["forecastRunId"]!=job["forecastRunId"]:raise ForecastOutcomeCommitError("Outcome identity is already used.","duplicate_forecast_outcome")
            if old_observation["submittedPayloadSha256"]!=observation["submittedPayloadSha256"] or _commit_sha(old_outcome)!=_commit_sha(outcome):raise ForecastOutcomeCommitError("Outcome retry evidence differs from the immutable commit.","outcome_retry_conflict")
            pointer=_publish_pointer(runtime_root,committed_root,commit,policy,commit["committedAt"]);shutil.rmtree(staging)
            return {"outcomeRoot":str(committed_root),"commit":commit,"pointer":pointer,"recovered":True}
        existing_records=[];included=[];evaluated_runs=set()
        for root in sorted((runtime_root/"forecast-outcomes").glob("*")):
            commit,prior_observation,prior,_=_verified_existing(root);prior_run=_run_id(prior);evaluated_runs.add(prior_run)
            if prior_run==job["forecastRunId"]:
                if prior_observation["submittedPayloadSha256"]==observation["submittedPayloadSha256"] and _commit_sha(prior)==_commit_sha(outcome):
                    pointer=_publish_pointer(runtime_root,root,commit,policy,commit["committedAt"]);shutil.rmtree(staging)
                    return {"outcomeRoot":str(root),"commit":commit,"pointer":pointer,"recovered":True}
                if prior_observation["observationRecordId"]==observation["observationRecordId"]:
                    raise ForecastOutcomeCommitError("The forecast already has conflicting committed outcome evidence.","correction_workflow_not_governed")
                raise ForecastOutcomeCommitError("The forecast already has committed outcome evidence.","duplicate_forecast_outcome")
            if prior_observation["observationRecordId"]==observation["observationRecordId"] and _observation_signature(prior_observation)!=_observation_signature(observation):raise ForecastOutcomeCommitError("Observation record identity conflicts with committed evidence.","conflicting_observation_record")
            prior["outcomeEvidenceSha256"]=commit["artifactHashes"]["outcome_evaluation.json"];existing_records.append(prior);included.append({"outcomeId":prior["outcomeId"],"outcomeEvidenceSha256":prior["outcomeEvidenceSha256"]})
        new_sha=sha256_file(artifacts/"outcome_evaluation.json");outcome["outcomeEvidenceSha256"]=new_sha;records=deterministic_outcome_sort([*existing_records,outcome]);included.append({"outcomeId":outcome["outcomeId"],"outcomeEvidenceSha256":new_sha})
        aggregate=aggregate_outcomes(records);allowed={"quick_forecast_p1"} if job["schemaVersion"]=="1.0" else set(policy["source_families"]);eligible_runs=_eligible_runs(runtime_root,outcome["evaluatedAt"],allowed)
        if any(_run_id(r) not in eligible_runs for r in records):raise ForecastOutcomeCommitError("Evaluated outcomes exceed eligible forecasts.","monitoring_count_error")
        version=job["schemaVersion"]
        limitations=["Synthetic benchmark outcome monitoring only; not operational surveillance.","Observed outcomes do not retrain, promote, or replace any model.","Empirical range coverage is historical evidence and not prediction-interval coverage."] if version=="1.0" else ["Evidence-only monitoring; no degradation classification is produced.","Observed outcomes do not promote, retain, replace, or roll back any model.","Missing actual observations are pending evidence, not integrity failures."]
        summary={"schemaVersion":version,"deploymentId":job["deploymentId"],"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy["policy_sha256"],"generatedAt":outcome["evaluatedAt"],"eligibilityAsOf":outcome["evaluatedAt"],**aggregate,"totalEligibleForecastCount":len(eligible_runs),"pendingOutcomeCount":len(eligible_runs-{_run_id(r) for r in records}),"modelBreakdowns":_breakdowns(records,lambda r:f"{r['modelId']}|{r['modelFamily']}|{r['modelParametersSha256']}"),"forecastPolicyBreakdowns":_breakdowns(records,lambda r:_policy_identity(_source_policy(r))),"uncertaintyStatusBreakdowns":_breakdowns(records,lambda r:r["empiricalRangeStatus"]),"includedOutcomes":sorted(included,key=lambda x:x["outcomeId"]),"outcomeSetSha256":deterministic_outcome_set_hash(records),"limitations":limitations}
        if version=="2.0":
            summary.update({"sourceFamilyBreakdowns":_breakdowns(records,lambda r:_source_family(r)),"monitoringPolicyBreakdowns":_breakdowns(records,lambda r:_policy_identity(r.get("monitoringPolicy",{"policyId":"RUNTIME.FORECAST_OUTCOME.MONITORING","policyVersion":"p1.4g-v1","policySha256":"0121c2fad28b7b8e9080df52698593d1cab677febf4fa668e11f6f19541fb249"}))),"assessmentPolicyBreakdowns":_breakdowns(records,lambda r:_policy_identity(r.get("sourceEvidence",{}).get("assessmentPolicy"))),"decisionPolicyBreakdowns":_breakdowns(records,lambda r:_policy_identity(r.get("sourceEvidence",{}).get("decisionPolicy"))),"latestSourceEvidence":{"sourceFamily":_source_family(outcome),"modelId":outcome["modelId"],"trainingRowCount":outcome.get("sourceEvidence",{}).get("trainingRowCount"),"plannedFoldCount":outcome.get("sourceEvidence",{}).get("plannedFoldCount"),"targetPeriod":outcome["forecastTargetPeriod"]}})
        atomic_json(artifacts/"monitoring_summary.json",summary);_validate(artifacts/"monitoring_summary.json",SCHEMAS["monitoring_summary.json"])
        hashes={name:sha256_file(artifacts/name) for name in SCHEMAS};committed_at=outcome["evaluatedAt"]
        commit={"schemaVersion":version,"outcomeId":job["outcomeId"],"jobId":job["jobId"],"forecastRunId":job["forecastRunId"],"sourceFamily":_source_family(outcome),"observationRecordId":observation["observationRecordId"],"deploymentId":job["deploymentId"],"policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy["policy_sha256"],"forecastCommitSha256":job["expectedForecastCommitSha256"],"status":"committed","artifactHashes":hashes,"latestForecastPointerModified":False,"profileModified":False,"authorizationModified":False,"committedAt":committed_at}
        if version=="1.0":
            for key in ("sourceFamily","profileModified","authorizationModified"):commit.pop(key)
        _schema_value(commit,"runtime_forecast_outcome_commit.schema.json");atomic_json(staging/"metadata/commit.json",commit)
        try:rechecked=verify_forecast_source(runtime_root,job["forecastRunId"],job["expectedForecastCommitSha256"],allowed)
        except ForecastSourceError as exc:raise ForecastOutcomeCommitError(str(exc),exc.code) from exc
        if rechecked["snapshot"]!=forecast_snapshot:raise ForecastOutcomeCommitError("Original forecast changed during outcome evaluation.","forecast_integrity_error")
        if (latest_path.read_bytes() if latest_path.exists() else None)!=latest_before or (monitoring_latest.read_bytes() if monitoring_latest.exists() else None)!=monitoring_before:raise ForecastOutcomeCommitError("Runtime pointer changed during outcome evaluation.","forecast_latest_pointer_changed")
        (runtime_root/"forecast-outcomes").mkdir(parents=True,exist_ok=True);_replace(staging,committed_root);pointer=_publish_pointer(runtime_root,committed_root,commit,policy,committed_at);_verified_existing(committed_root)
        if (latest_path.read_bytes() if latest_path.exists() else None)!=latest_before:raise ForecastOutcomeCommitError("Forecast latest pointer changed.","forecast_latest_pointer_changed")
        return {"outcomeRoot":str(committed_root),"commit":commit,"pointer":pointer,"recovered":False}
    finally:os.close(fd);lock_path.unlink(missing_ok=True)
