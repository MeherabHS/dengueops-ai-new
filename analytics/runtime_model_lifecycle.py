"""Stage a strict, neutral, human-governed lifecycle bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from runtime_active_model import FEATURE_SHA, PARAMETER_SHA, PROFILE_SHA, QUICK_SHA, REGISTRY_SHA, resolve_active_model
from runtime_commit import atomic_json
from runtime_model_lifecycle_policy import POLICY_ID, POLICY_SHA256, load_model_lifecycle_policy
from runtime_model_lifecycle_source import resolve_previous_assignment, verify_expected_pointer, verify_monitoring_and_degradation_context, verify_promotion_sources

ACK_FIELDS = ("manualActionAcknowledged","statisticalSufficiencyNotGovernedAcknowledged","materialWorseningNotClassifiedAcknowledged","evidenceDoesNotProveSuperiorityAcknowledged","quickCompatibleRandomForestOnlyAcknowledged")
ACKS = {field: True for field in ACK_FIELDS}
ASSIGNMENT_ACTIONS = {"bootstrap_historical_profile":"bootstrap","promote_selected_model":"promote","rollback_previous_assignment":"rollback"}


def json_sha(value: Mapping[str, Any]) -> str:
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def validate_schema(repository_root: Path, name: str, value: Mapping[str, Any]) -> None:
    schema = json.loads((repository_root / "config" / name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=lambda item:list(item.path))
    if errors:
        raise ValueError(f"lifecycle_schema_invalid:{name}:{errors[0].message}")


def verify_action_sources(repository_root: Path, runtime_root: Path, job: Mapping[str, Any], active: Mapping[str, Any]) -> dict[str, Any]:
    action = job["action"]
    if action == "bootstrap_historical_profile":
        if active["authoritySource"] != "historical_profile_fallback_pending_explicit_bootstrap" or job["expectedProfileSha256"] != PROFILE_SHA:
            raise ValueError("bootstrap_preconditions_failed")
        return {"expectedProfileSha256":PROFILE_SHA}
    if action == "promote_selected_model":
        return verify_promotion_sources(repository_root, runtime_root, job)
    if action == "rollback_previous_assignment":
        if active["authoritySource"] != "committed_assignment":
            raise ValueError("rollback_requires_committed_assignment")
        return resolve_previous_assignment(runtime_root, active)
    if action == "reject" and job.get("evidenceContextStatus") == "verified_assessment_and_decision":
        from runtime_model_lifecycle_source import verify_reject_assessment_decision
        return verify_reject_assessment_decision(repository_root,runtime_root,job)
    if action in {"retain_current_model","reject"} or (action == "defer" and job.get("evidenceContextStatus") == "verified_monitoring_and_degradation"):
        return verify_monitoring_and_degradation_context(repository_root, runtime_root, job, active)
    if action == "defer" and job.get("evidenceContextStatus") == "explicit_no_evidence":
        return {"evidenceContextStatus":"explicit_no_evidence"}
    raise ValueError("unsupported_lifecycle_action")


def deterministic_assignment_id(job: Mapping[str, Any]) -> str | None:
    if job["action"] not in ASSIGNMENT_ACTIONS:
        return None
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"dengueops:{POLICY_SHA256}:{job['lifecycleDecisionId']}:{job['action']}"))


def _evidence_fields(job: Mapping[str, Any]) -> dict[str, Any]:
    mapping = {
        "expectedProfileSha256":"profileSha256","evidenceContextStatus":"evidenceContextStatus",
        "expectedAssessmentCommitSha256":"assessmentCommitSha256","expectedDecisionCommitSha256":"decisionCommitSha256","expectedAuthorizationCommitSha256":"authorizationCommitSha256","expectedApprovedForecastCommitSha256":"approvedForecastCommitSha256","expectedOutcomeCommitSha256":"outcomeCommitSha256","expectedMonitoringLatestSha256":"monitoringLatestSha256","expectedMonitoringSummarySha256":"monitoringSummarySha256","expectedMonitoringIncludedOutcomeSetSha256":"monitoringIncludedOutcomeSetSha256","expectedDegradationLatestSha256":"degradationLatestSha256","expectedDegradationEvidenceCommitSha256":"degradationEvidenceCommitSha256","expectedDegradationEvidenceSha256":"degradationEvidenceSha256",
    }
    return {target:job[source] for source,target in mapping.items() if source in job}


def build_decision(job: Mapping[str, Any], active: Mapping[str, Any], verified: Mapping[str, Any], assignment_id: str | None) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "schemaVersion":"1.0","lifecycleDecisionId":job["lifecycleDecisionId"],"jobId":job["jobId"],"deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"target":"target_cases_next_2w","forecastHorizonWeeks":2,"policyId":POLICY_ID,"policyVersion":"p2-v1","policySha256":POLICY_SHA256,"action":job["action"],"operatorType":"trusted_internal","operatorIdentifier":job["operatorIdentifier"],"reason":job["reason"],
        **{field:True for field in ACK_FIELDS},"expectedAssignmentPointerState":job["expectedAssignmentPointerState"],"expectedAssignmentPointerSha256":job["expectedAssignmentPointerSha256"],"activeModelIdBefore":active["modelId"],"activeModelFamilyBefore":active["modelFamily"],"activeParameterSha256Before":active["parameterSha256"],"activeAuthoritySourceBefore":active["authoritySource"],"activeAuthoritySnapshotSha256Before":active["authoritySnapshotSha256"],"priorAssignmentId":active.get("assignmentId"),"priorAssignmentCommitSha256":active.get("assignmentCommitSha256"),"resultingAssignmentId":assignment_id,"modelIdentityChanged":False,"materialWorseningStatus":"not_governed","statisticalSufficiencyStatus":"not_governed","automaticAction":False,"createdAt":job["createdAt"],"decisionStatus":"committed",**_evidence_fields(job),
    }
    if job["action"] == "promote_selected_model":
        decision.update({"assessmentId":verified["sourceAssessmentId"],"sourceDecisionId":verified["sourceDecisionId"],"authorizationId":verified["sourceAuthorizationId"],"approvedForecastRunId":verified["sourceApprovedForecastId"],"outcomeId":verified["sourceOutcomeId"],"degradationEvidenceId":verified["sourceDegradationEvidenceId"],"assessmentReferenceCohortId":verified["assessmentReferenceCohortId"],"assessmentReferenceDimensionId":verified["assessmentReferenceDimensionId"],"selectedModelId":verified["selectedModelId"],"selectedModelFamily":verified["selectedModelFamily"],"selectedParameterSha256":verified["selectedModelParameterSha256"],"candidateRegistrySha256":verified["candidateRegistrySha256"],"featureOrderSha256":verified["featureOrderSha256"]})
    elif job["action"] == "rollback_previous_assignment":
        decision.update({"rollbackSourceAssignmentId":verified["assignment"]["assignmentId"],"rollbackSourceAssignmentCommitSha256":verified["commitSha256"]})
    return decision


def build_decision_commit(job: Mapping[str, Any], decision: Mapping[str, Any], verified: Mapping[str, Any]) -> dict[str, Any]:
    commit: dict[str, Any] = {"schemaVersion":"1.0","lifecycleDecisionId":job["lifecycleDecisionId"],"jobId":job["jobId"],"policyId":POLICY_ID,"policyVersion":"p2-v1","policySha256":POLICY_SHA256,"action":job["action"],"inputAssignmentPointerState":job["expectedAssignmentPointerState"],"inputAssignmentPointerSha256":job["expectedAssignmentPointerSha256"],"lifecycleDecisionSha256":json_sha(decision),"operatorIdentitySource":"server_configuration","committedAt":job["createdAt"],"status":"committed","profileModified":False,"forecastLatestModified":False,"monitoringLatestModified":False,"degradationLatestModified":False,"authorizationModified":False,"automaticActionProduced":False}
    if job["action"] == "bootstrap_historical_profile": commit["profileSha256"] = PROFILE_SHA
    elif job["action"] == "promote_selected_model":
        for source,target in (("expectedAssessmentCommitSha256","assessmentCommitSha256"),("expectedDecisionCommitSha256","decisionCommitSha256"),("expectedAuthorizationCommitSha256","authorizationCommitSha256"),("expectedApprovedForecastCommitSha256","approvedForecastCommitSha256"),("expectedOutcomeCommitSha256","outcomeCommitSha256"),("expectedMonitoringLatestSha256","monitoringLatestSha256"),("expectedMonitoringSummarySha256","monitoringSummarySha256"),("expectedMonitoringIncludedOutcomeSetSha256","monitoringIncludedOutcomeSetSha256"),("expectedDegradationLatestSha256","degradationLatestSha256"),("expectedDegradationEvidenceCommitSha256","degradationEvidenceCommitSha256"),("expectedDegradationEvidenceSha256","degradationEvidenceSha256")): commit[target]=job[source]
    elif job["action"] == "reject" and job["evidenceContextStatus"] == "verified_assessment_and_decision":
        commit.update({"evidenceContextStatus":"verified_assessment_and_decision","assessmentCommitSha256":job["expectedAssessmentCommitSha256"],"decisionCommitSha256":job["expectedDecisionCommitSha256"]})
    elif job["action"] in {"retain_current_model","reject"} or (job["action"] == "defer" and job["evidenceContextStatus"] == "verified_monitoring_and_degradation"):
        commit.update({"evidenceContextStatus":"verified_monitoring_and_degradation","monitoringLatestSha256":job["expectedMonitoringLatestSha256"],"monitoringSummarySha256":job["expectedMonitoringSummarySha256"],"monitoringIncludedOutcomeSetSha256":job["expectedMonitoringIncludedOutcomeSetSha256"],"degradationLatestSha256":job["expectedDegradationLatestSha256"],"degradationEvidenceCommitSha256":job["expectedDegradationEvidenceCommitSha256"],"degradationEvidenceSha256":job["expectedDegradationEvidenceSha256"]})
    elif job["action"] == "defer": commit["evidenceContextStatus"] = "explicit_no_evidence"
    elif job["action"] == "rollback_previous_assignment": commit.update({"rollbackSourceAssignmentId":verified["assignment"]["assignmentId"],"rollbackSourceAssignmentCommitSha256":verified["commitSha256"]})
    return commit


def build_assignment(job: Mapping[str, Any], active: Mapping[str, Any], verified: Mapping[str, Any], assignment_id: str, decision_commit_sha: str) -> dict[str, Any]:
    action = ASSIGNMENT_ACTIONS[job["action"]]
    assignment: dict[str, Any] = {"schemaVersion":"1.0","assignmentId":assignment_id,"assignmentReason":{"bootstrap":"historical_profile_bootstrap","promote":"manual_selected_model_promotion","rollback":"controlled_previous_assignment_rollback"}[action],"deploymentId":"dhaka_south","geography":{"level":"city","id":"BGD-DHAKA-SOUTH","name":"Dhaka South"},"target":"target_cases_next_2w","forecastHorizonWeeks":2,"policyId":POLICY_ID,"policyVersion":"p2-v1","policySha256":POLICY_SHA256,"lifecycleDecisionId":job["lifecycleDecisionId"],"lifecycleDecisionCommitSha256":decision_commit_sha,"assignmentAction":action,"assignedModelId":"random_forest","modelFamily":"RandomForestRegressor","parameterSha256":PARAMETER_SHA,"featureOrderSha256":FEATURE_SHA,"candidateRegistrySha256":REGISTRY_SHA,"quickForecastPolicyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","quickForecastPolicyVersion":"p1.4f-v1","quickForecastPolicySha256":QUICK_SHA,"quickCompatibilityStatus":"compatible_exact_governed_random_forest","priorAssignmentId":active.get("assignmentId"),"priorAssignmentCommitSha256":active.get("assignmentCommitSha256"),"effectiveAt":job["createdAt"],"assignmentStatus":"committed","modelQualificationStatus":"not_governed","materialWorseningStatus":"not_governed","statisticalSufficiencyStatus":"not_governed","automaticAction":False,"modelIdentityChanged":False}
    if action == "bootstrap": assignment["profileRawSha256"] = PROFILE_SHA
    elif action == "promote":
        for key in ("sourceAssessmentId","sourceAssessmentCommitSha256","sourceDecisionId","sourceDecisionArtifactSha256","sourceDecisionCommitSha256","sourceAuthorizationId","sourceAuthorizationRecordSha256","sourceAuthorizationCommitSha256","sourceAuthorizationConsumptionSha256","sourceApprovedForecastId","sourceApprovedForecastCommitSha256","sourceOutcomeId","sourceOutcomeCommitSha256","sourceMonitoringLatestSha256","sourceMonitoringSummarySha256","sourceMonitoringIncludedOutcomeSetSha256","sourceDegradationLatestSha256","sourceDegradationEvidenceId","sourceDegradationEvidenceCommitSha256","sourceDegradationEvidenceSha256","assessmentReferenceCohortId","assessmentReferenceDimensionId"): assignment[key]=verified[key]
    else: assignment.update({"rollbackSourceAssignmentId":verified["assignment"]["assignmentId"],"rollbackSourceAssignmentCommitSha256":verified["commitSha256"]})
    return assignment


def build_assignment_commit(job: Mapping[str, Any], assignment: Mapping[str, Any], decision_commit_sha: str) -> dict[str, Any]:
    commit: dict[str, Any] = {"schemaVersion":"1.0","assignmentId":assignment["assignmentId"],"assignmentAction":assignment["assignmentAction"],"assignmentSha256":json_sha(assignment),"lifecycleDecisionId":job["lifecycleDecisionId"],"lifecycleDecisionCommitSha256":decision_commit_sha,"priorPointerSha256":job["expectedAssignmentPointerSha256"],"priorAssignmentId":assignment["priorAssignmentId"],"priorAssignmentCommitSha256":assignment["priorAssignmentCommitSha256"],"assignedModelId":"random_forest","modelFamily":"RandomForestRegressor","parameterSha256":PARAMETER_SHA,"featureOrderSha256":FEATURE_SHA,"candidateRegistrySha256":REGISTRY_SHA,"quickForecastPolicyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","quickForecastPolicyVersion":"p1.4f-v1","quickForecastPolicySha256":QUICK_SHA,"publicationEligible":True,"committedAt":job["createdAt"],"status":"committed","profileModified":False,"forecastLatestModified":False,"monitoringLatestModified":False,"degradationLatestModified":False,"authorizationModified":False,"automaticActionProduced":False}
    if assignment["assignmentAction"] == "bootstrap": commit["profileRawSha256"] = PROFILE_SHA
    elif assignment["assignmentAction"] == "promote":
        for key in ("sourceAssessmentCommitSha256","sourceDecisionArtifactSha256","sourceDecisionCommitSha256","sourceAuthorizationRecordSha256","sourceAuthorizationCommitSha256","sourceAuthorizationConsumptionSha256","sourceApprovedForecastCommitSha256","sourceOutcomeCommitSha256","sourceMonitoringLatestSha256","sourceMonitoringSummarySha256","sourceMonitoringIncludedOutcomeSetSha256","sourceDegradationLatestSha256","sourceDegradationEvidenceCommitSha256","sourceDegradationEvidenceSha256"): commit[key]=assignment[key]
    else: commit.update({"rollbackSourceAssignmentId":assignment["rollbackSourceAssignmentId"],"rollbackSourceAssignmentCommitSha256":assignment["rollbackSourceAssignmentCommitSha256"]})
    return commit


def prepare_bundle(repository_root: Path, runtime_root: Path, job: Mapping[str, Any], active: Mapping[str, Any], verified: Mapping[str, Any]) -> dict[str, dict[str, Any] | None]:
    assignment_id = deterministic_assignment_id(job); decision = build_decision(job, active, verified, assignment_id); decision_commit = build_decision_commit(job, decision, verified); decision_commit_sha = json_sha(decision_commit)
    assignment = build_assignment(job, active, verified, assignment_id, decision_commit_sha) if assignment_id else None
    assignment_commit = build_assignment_commit(job, assignment, decision_commit_sha) if assignment else None
    for value,name in ((decision,"runtime_model_lifecycle_decision.schema.json"),(decision_commit,"runtime_model_lifecycle_decision_commit.schema.json"),(assignment,"runtime_model_assignment.schema.json"),(assignment_commit,"runtime_model_assignment_commit.schema.json")):
        if value is not None: validate_schema(repository_root,name,value)
    return {"decision":decision,"decisionCommit":decision_commit,"assignment":assignment,"assignmentCommit":assignment_commit}


def execute(job_path: Path, runtime_root: Path, staging: Path, repository_root: Path) -> dict[str, Any]:
    job = json.loads(job_path.read_text(encoding="utf-8")); validate_schema(repository_root,"runtime_job.schema.json",job); load_model_lifecycle_policy(repository_root); verify_expected_pointer(job,runtime_root)
    from runtime_model_lifecycle_commit import recover_committed_bundle
    recovered = recover_committed_bundle(repository_root,runtime_root,job)
    if recovered is not None: return recovered
    active = resolve_active_model(repository_root,runtime_root); verified = verify_action_sources(repository_root,runtime_root,job,active); bundle = prepare_bundle(repository_root,runtime_root,job,active,verified)
    (staging/"artifacts").mkdir(parents=True,exist_ok=False); (staging/"metadata").mkdir(parents=True,exist_ok=False)
    atomic_json(staging/"artifacts/lifecycle_decision.json",bundle["decision"]); atomic_json(staging/"metadata/lifecycle_decision_commit.json",bundle["decisionCommit"])
    if bundle["assignment"] is not None:
        atomic_json(staging/"artifacts/model_assignment.json",bundle["assignment"]); atomic_json(staging/"metadata/model_assignment_commit.json",bundle["assignmentCommit"])
    from runtime_model_lifecycle_commit import commit_lifecycle
    return commit_lifecycle(repository_root,runtime_root,job_path,staging)


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--runtime-root",required=True); parser.add_argument("--job-record",required=True); parser.add_argument("--staging",required=True); args=parser.parse_args()
    try: print(json.dumps(execute(Path(args.job_record),Path(args.runtime_root),Path(args.staging),Path(__file__).resolve().parents[1]),separators=(",",":"))); return 0
    except Exception as exc: print(json.dumps({"ok":False,"code":"model_lifecycle_failed","message":str(exc)}),file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
