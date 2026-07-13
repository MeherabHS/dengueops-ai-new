"""Validate and atomically commit one decision-authorized forecast run."""
from __future__ import annotations
import json, os, stat, time, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker
from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within

SCHEMAS={"metadata/run.json":"runtime_approved_forecast_run.schema.json","artifacts/forecast_output.json":"runtime_approved_forecast_output.schema.json","artifacts/forecast_uncertainty.json":"runtime_approved_forecast_uncertainty.schema.json","artifacts/dashboard_summary.json":"runtime_approved_forecast_dashboard.schema.json","artifacts/model_card.json":"runtime_approved_forecast_model_card.schema.json"}
REQUIRED={"input_manifest.json","model_features.csv","forecast_output.json","forecast_uncertainty.json","model_card.json","dashboard_summary.json","chart_data.json","pipeline_run_summary.json"}
PROHIBITED={"candidate_model_comparison.json","rolling_validation.json","recommendation.json","directives.json","preparedness.json","planning_scenarios.json","facility_projections.json","inventory_alerts.json","alerts.json"}
class ApprovedForecastCommitError(RuntimeError): pass
def _json(path:Path)->dict[str,Any]:
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:raise ApprovedForecastCommitError(f"Invalid approved forecast JSON: {path.name}.") from exc
    if not isinstance(value,dict):raise ApprovedForecastCommitError(f"Approved forecast JSON must be an object: {path.name}.")
    return value
def _validate(path:Path,schema:str)->dict[str,Any]:
    value=_json(path); definition=_json(ROOT/"config"/schema); errors=sorted(Draft202012Validator(definition,format_checker=FormatChecker()).iter_errors(value),key=lambda e:list(e.path))
    if errors:raise ApprovedForecastCommitError(f"{path.name} failed schema validation: {errors[0].message}")
    return value
def _lock(path:Path)->int:
    path.parent.mkdir(parents=True,exist_ok=True); deadline=time.monotonic()+30
    while True:
        try:return os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:
            if time.monotonic()>deadline:raise ApprovedForecastCommitError("Deployment commit lock timed out.")
            time.sleep(.1)
def _fsync(path:Path):
    if os.name=="nt":return
    fd=os.open(path,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
def _immutable(root:Path):
    if os.name=="nt":return
    for p in sorted(root.rglob("*"),reverse=True):p.chmod(0o555 if p.is_dir() else 0o444)
    root.chmod(0o555)
def commit_approved_forecast(runtime_root:Path,staging_path:Path,job:dict[str,Any])->dict[str,Any]:
    root=require_absolute_directory(runtime_root,"runtime root"); staging=require_within(root,staging_path,"approved forecast staging")
    if staging.parent!=(root/"staging").resolve() or staging.name!=job["runId"]:raise ApprovedForecastCommitError("Approved forecast staging identity mismatch.")
    artifacts=staging/"artifacts"; present={p.name for p in artifacts.iterdir()}; missing=REQUIRED-present; prohibited=PROHIBITED&present
    if missing or prohibited:raise ApprovedForecastCommitError(f"Invalid approved forecast artifact set; missing={sorted(missing)}, prohibited={sorted(prohibited)}")
    values={rel:_validate(staging/rel,schema) for rel,schema in SCHEMAS.items()}; run=values["metadata/run.json"]; forecast=values["artifacts/forecast_output.json"]; uncertainty=values["artifacts/forecast_uncertainty.json"]; dashboard=values["artifacts/dashboard_summary.json"]; card=values["artifacts/model_card.json"]
    for value in (run,forecast):
        for key in ("runId","jobId","datasetId","deploymentId","decisionId","assessmentId","authorizationId"):
            if value.get(key)!=job.get(key):raise ApprovedForecastCommitError(f"Approved forecast identity mismatch: {key}.")
    for key in ("runId","jobId","datasetId","deploymentId","decisionId","assessmentId"):
        if uncertainty.get(key)!=job.get(key):raise ApprovedForecastCommitError(f"Approved uncertainty identity mismatch: {key}.")
    if any(card.get(key)!=job.get(key) for key in ("runId","jobId","datasetId","deploymentId")) or card.get("decision",{}).get("id")!=job["decisionId"] or card.get("assessment",{}).get("id")!=job["assessmentId"] or card.get("authorization",{}).get("id")!=job["authorizationId"]:raise ApprovedForecastCommitError("Approved model-card identity mismatch.")
    if forecast["selectedModelId"]!=job["selectedModelId"] or forecast["selectedModelParameterSha256"]!=job["selectedModelParameterSha256"] or forecast["deploymentModelAdopted"] is not False:raise ApprovedForecastCommitError("Selected model or adoption identity mismatch.")
    if any(uncertainty.get(k) is not None for k in ("lowerRaw","upperRaw","lowerReported","upperReported","nominalCoverage","historicalCoverage","calibrationMethod","residualCount")) or uncertainty.get("isPredictionInterval") is not False or uncertainty.get("rmseFallbackAllowed") is not False or uncertainty.get("bundledP13RangeReused") is not False:raise ApprovedForecastCommitError("Approved forecast uncertainty must remain null and uncalibrated.")
    if dashboard.get("preparedness")!={"availabilityStatus":"unavailable_missing_planning_policy","scenarios":None,"counts":None,"facilities":[],"alerts":[]}:raise ApprovedForecastCommitError("Approved forecast preparedness must remain unavailable.")
    auth_root=require_within(root,root/"authorizations"/job["authorizationId"],"authorization"); state=require_within(root,root/"authorization-state"/job["authorizationId"],"authorization state"); reservation=_json(state/"reservation.json")
    if reservation.get("jobId")!=job["jobId"] or reservation.get("runId")!=job["runId"] or reservation.get("eventType")!="reserved" or (state/"consumption.json").exists():raise ApprovedForecastCommitError("One-run authorization reservation is invalid or consumed.")
    if sha256_file(root/"decisions"/job["decisionId"]/"commit.json")!=job["decisionCommitSha256"] or sha256_file(root/"assessments"/job["assessmentId"]/"metadata"/"commit.json")!=job["assessmentCommitSha256"]:raise ApprovedForecastCommitError("Decision or assessment commit binding changed.")
    hashes={name:sha256_file(artifacts/name) for name in sorted(REQUIRED)}
    for name,digest in hashes.items():
        if name!="model_card.json" and card["artifactHashes"].get(name)!=digest:raise ApprovedForecastCommitError(f"Model-card artifact hash mismatch: {name}.")
    if run["artifactPublicationSequence"][-1]!="model_card.json":raise ApprovedForecastCommitError("Approved forecast model card was not published last.")
    committed_at=datetime.now(timezone.utc).isoformat().replace("+00:00","Z"); commit={"schemaVersion":"1.0","runId":job["runId"],"jobId":job["jobId"],"datasetId":job["datasetId"],"deploymentId":job["deploymentId"],"workflowMode":"approved_assessment_forecast","sourceType":"uploaded","decisionId":job["decisionId"],"decisionCommitSha256":job["decisionCommitSha256"],"assessmentId":job["assessmentId"],"assessmentCommitSha256":job["assessmentCommitSha256"],"authorizationId":job["authorizationId"],"selectedModelId":job["selectedModelId"],"selectedModelParameterSha256":job["selectedModelParameterSha256"],"decisionScope":"one_run","deploymentModelAdopted":False,"status":"committed","artifactHashes":hashes,"modelCardPublishedLast":True,"prohibitedArtifactsAbsent":True,"committedAt":committed_at}
    Draft202012Validator(_json(ROOT/"config"/"runtime_approved_forecast_commit.schema.json"),format_checker=FormatChecker()).validate(commit); atomic_json(staging/"metadata"/"commit.json",commit)
    runs=(root/"runs").resolve(); runs.mkdir(parents=True,exist_ok=True); committed=runs/job["runId"]
    if committed.exists():raise ApprovedForecastCommitError("Immutable approved forecast run already exists.")
    os.replace(staging,committed);_fsync(runs);_immutable(committed)
    deployment=root/"deployments"/job["deploymentId"]; lock_path=deployment/"locks"/"commit.lock";fd=_lock(lock_path)
    try:
        pointer={"schemaVersion":"1.0","deploymentId":job["deploymentId"],"runId":job["runId"],"datasetId":job["datasetId"],"workflowMode":"approved_assessment_forecast","sourceType":"uploaded","decisionId":job["decisionId"],"assessmentId":job["assessmentId"],"authorizationId":job["authorizationId"],"selectedModelId":job["selectedModelId"],"committedAt":committed_at,"modelCardSha256":sha256_file(committed/"artifacts"/"model_card.json"),"dashboardSummarySha256":sha256_file(committed/"artifacts"/"dashboard_summary.json"),"commitRecordSha256":sha256_file(committed/"metadata"/"commit.json")}
        Draft202012Validator(_json(ROOT/"config"/"runtime_latest.schema.json"),format_checker=FormatChecker()).validate(pointer);deployment.mkdir(parents=True,exist_ok=True);atomic_json(deployment/"latest.json",pointer);_fsync(deployment)
    finally:os.close(fd);lock_path.unlink(missing_ok=True)
    consumption={"schemaVersion":"1.0","authorizationId":job["authorizationId"],"decisionId":job["decisionId"],"eventType":"consumed","eventId":str(uuid.uuid4()),"createdAt":committed_at,"jobId":job["jobId"],"runId":job["runId"]}
    try:atomic_json(state/"consumption.json",consumption)
    except Exception:pass
    return {"runRoot":str(committed),"pointer":pointer,"commit":commit}
