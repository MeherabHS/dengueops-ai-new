"""Independent immutable commit for evidence-only degradation comparisons."""
from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from runtime_commit import atomic_json, sha256_file
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_model_degradation_policy import load_and_validate_model_degradation_policy
from runtime_model_degradation_source import verify_model_degradation_source


class ModelDegradationCommitError(RuntimeError):
    pass


def _json(path:Path)->dict[str,Any]:
    try:value=json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:raise ModelDegradationCommitError(f"Invalid JSON: {path.name}.") from exc
    if not isinstance(value,dict):raise ModelDegradationCommitError(f"{path.name} must be an object.")
    return value
def _schema(value:Mapping[str,Any],name:str)->None:
    schema=_json(ROOT/"config"/name);errors=sorted(Draft202012Validator(schema,format_checker=FormatChecker()).iter_errors(value),key=lambda error:list(error.path))
    if errors:raise ModelDegradationCommitError(f"{name}: {errors[0].message}")
def _lock(path:Path,timeout:float=30)->int:
    path.parent.mkdir(parents=True,exist_ok=True);deadline=time.monotonic()+timeout
    while True:
        try:return os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError:
            if time.monotonic()>=deadline:raise ModelDegradationCommitError("Degradation commit lock timed out.")
            time.sleep(.05)
def _tree_hashes(root:Path)->dict[str,str]:
    if not root.exists():return {}
    return {str(path.relative_to(root)).replace("\\","/"):sha256_file(path) for path in sorted(root.rglob("*")) if path.is_file()}
def _bytes(path:Path)->bytes|None:return path.read_bytes() if path.is_file() else None


def _verify_committed(root:Path)->tuple[dict[str,Any],dict[str,Any],dict[str,Any]]:
    commit=_json(root/"metadata/commit.json");evidence=_json(root/"artifacts/degradation_evidence.json");summary=_json(root/"artifacts/degradation_summary.json")
    _schema(commit,"runtime_model_degradation_commit.schema.json");_schema(evidence,"runtime_model_degradation_evidence.schema.json");_schema(summary,"runtime_model_degradation_summary.schema.json")
    if commit["artifactHashes"]!={"degradation_evidence.json":sha256_file(root/"artifacts/degradation_evidence.json"),"degradation_summary.json":sha256_file(root/"artifacts/degradation_summary.json")} or commit["evidenceId"]!=evidence["evidenceId"] or summary["evidenceId"]!=evidence["evidenceId"]:raise ModelDegradationCommitError("Committed degradation artifacts failed integrity verification.")
    return commit,evidence,summary


def _publish_pointer(runtime_root:Path,committed:Path,commit:Mapping[str,Any],published_at:str)->dict[str,Any]:
    evidence_path=committed/"artifacts/degradation_evidence.json";summary_path=committed/"artifacts/degradation_summary.json";commit_path=committed/"metadata/commit.json";evidence_id=str(commit["evidenceId"])
    pointer={"schemaVersion":"1.0","evidenceId":evidence_id,"deploymentId":"dhaka_south","policyId":commit["policyId"],"policyVersion":commit["policyVersion"],"policySha256":commit["policySha256"],"monitoringPolicyId":commit["monitoringPolicyId"],"monitoringPolicyVersion":commit["monitoringPolicyVersion"],"monitoringPolicySha256":commit["monitoringPolicySha256"],"monitoringLatestInputSha256":commit["monitoringLatestSha256"],"monitoringSummaryInputSha256":commit["monitoringSummarySha256"],"includedOutcomeSetSha256":commit["includedOutcomeSetSha256"],"evidencePath":f"degradation-evidence/{evidence_id}/artifacts/degradation_evidence.json","evidenceSha256":sha256_file(evidence_path),"summaryPath":f"degradation-evidence/{evidence_id}/artifacts/degradation_summary.json","summarySha256":sha256_file(summary_path),"commitPath":f"degradation-evidence/{evidence_id}/metadata/commit.json","commitSha256":sha256_file(commit_path),"publishedAt":published_at,"evidenceStatus":"evidence_only","materialWorseningStatus":"not_governed","lifecycleActionStatus":"prohibited_not_generated"}
    _schema(pointer,"runtime_model_degradation_latest.schema.json");path=runtime_root/"deployments/dhaka_south/degradation/latest.json";path.parent.mkdir(parents=True,exist_ok=True);atomic_json(path,pointer);return pointer


def commit_model_degradation_evidence(runtime_root:Path,staging_path:Path,job:dict[str,Any],policy:dict[str,Any])->dict[str,Any]:
    root=require_absolute_directory(runtime_root,"runtime root");staging=require_within(root,staging_path,"degradation staging")
    if staging.parent!=(root/"degradation-staging").resolve() or staging.name!=job["evidenceId"]:raise ModelDegradationCommitError("Degradation staging identity mismatch.")
    evidence_path=staging/"artifacts/degradation_evidence.json";summary_path=staging/"artifacts/degradation_summary.json";evidence=_json(evidence_path);summary=_json(summary_path);_schema(evidence,"runtime_model_degradation_evidence.schema.json");_schema(summary,"runtime_model_degradation_summary.schema.json")
    checked_policy,policy_sha=load_and_validate_model_degradation_policy(job["deploymentId"],job["schemaVersion"],job["policyVersion"],job["policySha256"])
    if checked_policy!=policy:raise ModelDegradationCommitError("Degradation policy changed during generation.")
    source=verify_model_degradation_source(root,job["expectedMonitoringLatestSha256"],job["expectedMonitoringSummarySha256"],job["expectedIncludedOutcomeSetSha256"])
    from runtime_model_degradation_evidence import build_model_degradation_evidence
    expected_evidence,expected_summary=build_model_degradation_evidence(job,policy,policy_sha,source,evidence["generatedAt"])
    if evidence!=expected_evidence or summary!=expected_summary:raise ModelDegradationCommitError("Staged degradation evidence does not reconcile.")
    monitoring_path=root/"deployments/dhaka_south/monitoring/latest.json";forecast_path=root/"deployments/dhaka_south/latest.json";profile_path=ROOT/"config/deployments/dhaka_south/profile.json";authorization_root=root/"authorization-state"
    monitoring_before=_bytes(monitoring_path);forecast_before=_bytes(forecast_path);profile_before=_bytes(profile_path);authorization_before=_tree_hashes(authorization_root)
    lock_path=root/"deployments/dhaka_south/degradation/locks/commit.lock";fd=_lock(lock_path)
    try:
        collection=root/"degradation-evidence";committed=collection/job["evidenceId"]
        if committed.exists():
            old_commit,_,_=_verify_committed(committed)
            if (old_commit["policySha256"],old_commit["monitoringLatestSha256"],old_commit["monitoringSummarySha256"],old_commit["includedOutcomeSetSha256"])!=(policy_sha,source["latestSha256"],source["summarySha256"],source["summary"]["outcomeSetSha256"]):raise ModelDegradationCommitError("Degradation evidence identity conflict.")
            pointer=_publish_pointer(root,committed,old_commit,old_commit["committedAt"]);shutil.rmtree(staging);return{"commit":old_commit,"pointer":pointer,"recovered":True,"evidenceRoot":str(committed)}
        for candidate in sorted(collection.glob("*")) if collection.exists() else []:
            try:old_commit,_,_=_verify_committed(candidate)
            except Exception:continue
            if (old_commit["policySha256"],old_commit["monitoringLatestSha256"],old_commit["monitoringSummarySha256"],old_commit["includedOutcomeSetSha256"])==(policy_sha,source["latestSha256"],source["summarySha256"],source["summary"]["outcomeSetSha256"]):
                pointer=_publish_pointer(root,candidate,old_commit,old_commit["committedAt"]);shutil.rmtree(staging);return{"commit":old_commit,"pointer":pointer,"recovered":True,"evidenceRoot":str(candidate)}
        assessment_refs=sorted({(value["assessmentId"],value["assessmentCommitSha256"],value["candidateComparisonSha256"]) for value in source["assessmentReferences"].values()})
        committed_at=evidence["generatedAt"];commit={"schemaVersion":"1.0","evidenceId":job["evidenceId"],"jobId":job["jobId"],"deploymentId":"dhaka_south","policyId":policy["policy_id"],"policyVersion":policy["policy_version"],"policySha256":policy_sha,"monitoringPolicyId":"RUNTIME.FORECAST_OUTCOME.MONITORING","monitoringPolicyVersion":"p2-v1","monitoringPolicySha256":policy["accepted_monitoring_policy"]["policy_sha256"],"monitoringLatestPath":source["latestPath"],"monitoringLatestSha256":source["latestSha256"],"monitoringSummaryPath":source["summaryPath"],"monitoringSummarySha256":source["summarySha256"],"includedOutcomeSetSha256":source["summary"]["outcomeSetSha256"],"includedOutcomes":source["includedOutcomes"],"assessmentReferences":[{"assessmentId":a,"assessmentCommitSha256":b,"candidateComparisonSha256":c} for a,b,c in assessment_refs],"includedCohortSetSha256":evidence["includedCohortSetSha256"],"artifactHashes":{"degradation_evidence.json":sha256_file(evidence_path),"degradation_summary.json":sha256_file(summary_path)},"status":"committed","monitoringLatestModified":False,"forecastLatestModified":False,"profileModified":False,"deploymentModelModified":False,"authorizationModified":False,"lifecycleActionProduced":False,"committedAt":committed_at}
        _schema(commit,"runtime_model_degradation_commit.schema.json");atomic_json(staging/"metadata/commit.json",commit)
        rechecked=verify_model_degradation_source(root,source["latestSha256"],source["summarySha256"],source["summary"]["outcomeSetSha256"])
        if rechecked["includedOutcomes"]!=source["includedOutcomes"] or _bytes(monitoring_path)!=monitoring_before or _bytes(forecast_path)!=forecast_before or _bytes(profile_path)!=profile_before or _tree_hashes(authorization_root)!=authorization_before:raise ModelDegradationCommitError("Protected runtime input changed during degradation generation.")
        collection.mkdir(parents=True,exist_ok=True);os.replace(staging,committed);_verify_committed(committed);pointer=_publish_pointer(root,committed,commit,committed_at)
        if _bytes(monitoring_path)!=monitoring_before or _bytes(forecast_path)!=forecast_before or _bytes(profile_path)!=profile_before or _tree_hashes(authorization_root)!=authorization_before:raise ModelDegradationCommitError("Degradation publication modified protected state.")
        return{"commit":commit,"pointer":pointer,"recovered":False,"evidenceRoot":str(committed)}
    finally:os.close(fd);lock_path.unlink(missing_ok=True)
