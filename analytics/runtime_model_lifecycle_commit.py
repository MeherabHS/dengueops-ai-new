"""Independent lifecycle reconciliation, immutable publication, and orphan recovery."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from feature_engineering import FEATURE_COLUMNS
from runtime_active_model import FEATURE_SHA, PARAMETER_SHA, PROFILE_SHA, QUICK_SHA, REGISTRY_SHA, resolve_active_model
from runtime_commit import atomic_json
from runtime_model_lifecycle import prepare_bundle, validate_schema, verify_action_sources
from runtime_model_lifecycle_policy import POLICY_ID, POLICY_SHA256, canonical_sha256, load_model_lifecycle_policy
from runtime_model_lifecycle_source import assignment_pointer_state, verify_expected_pointer


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file(): raise ValueError("lifecycle_commit_artifact_missing_or_unsafe")
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError("lifecycle_commit_artifact_not_object")
    return value


def _tree_hash(path: Path) -> str:
    if not path.exists(): return "ABSENT"
    rows=[]
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()): rows.append(f"{item.relative_to(path).as_posix()}:{sha(item)}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def _feature_order_identity(repository_root: Path) -> str:
    """Recompute and reconcile the executable feature order independently."""
    computed=hashlib.sha256(json.dumps(list(FEATURE_COLUMNS),sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    registry=_json(repository_root/"config/candidate_models.json")
    quick=_json(repository_root/"config/deployments/dhaka_south/quick_forecast_policy.json")
    lifecycle=_json(repository_root/"config/deployments/dhaka_south/model_lifecycle_policy.json")
    identities=(
        computed,
        FEATURE_SHA,
        registry.get("feature_order_sha256"),
        quick.get("feature_contract",{}).get("feature_order_sha256"),
        lifecycle.get("feature_order_sha256"),
    )
    if any(identity != FEATURE_SHA for identity in identities):
        raise ValueError("protected_feature_order_identity_invalid")
    return computed


def _protected_state(repository_root: Path, runtime_root: Path) -> dict[str,str]:
    paths={"profile":repository_root/"config/deployments/dhaka_south/profile.json","candidateRegistry":repository_root/"config/candidate_models.json","featureEngineering":repository_root/"analytics/feature_engineering.py","quickPolicy":repository_root/"config/deployments/dhaka_south/quick_forecast_policy.json","forecastLatest":runtime_root/"deployments/dhaka_south/latest.json","monitoringLatest":runtime_root/"deployments/dhaka_south/monitoring/latest.json","degradationLatest":runtime_root/"deployments/dhaka_south/degradation/latest.json"}
    result={key:(sha(path) if path.is_file() else "ABSENT") for key,path in paths.items()}
    result["featureOrderIdentity"]=_feature_order_identity(repository_root)
    result["authorizationState"]=_tree_hash(runtime_root/"authorization-state")
    return result


def _assignment_bundles(runtime_root: Path) -> list[Path]:
    root=runtime_root/"model-lifecycle"
    if not root.exists(): return []
    if root.is_symlink() or not root.is_dir(): raise ValueError("unsafe_lifecycle_history")
    bundles=[]
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir(): raise ValueError("unsafe_lifecycle_history")
        assignment=candidate/"artifacts/model_assignment.json"; commit=candidate/"metadata/model_assignment_commit.json"
        if assignment.exists() or commit.exists():
            if not assignment.is_file() or assignment.is_symlink() or not commit.is_file() or commit.is_symlink(): raise ValueError("incomplete_assignment_history")
            bundles.append(candidate)
    return bundles


def _load_bundle(repository_root: Path, root: Path, assignment_expected: bool) -> dict[str,Any]:
    decision=_json(root/"artifacts/lifecycle_decision.json"); decision_commit=_json(root/"metadata/lifecycle_decision_commit.json")
    validate_schema(repository_root,"runtime_model_lifecycle_decision.schema.json",decision); validate_schema(repository_root,"runtime_model_lifecycle_decision_commit.schema.json",decision_commit)
    assignment=assignment_commit=None
    if assignment_expected:
        assignment=_json(root/"artifacts/model_assignment.json"); assignment_commit=_json(root/"metadata/model_assignment_commit.json")
        validate_schema(repository_root,"runtime_model_assignment.schema.json",assignment); validate_schema(repository_root,"runtime_model_assignment_commit.schema.json",assignment_commit)
    elif (root/"artifacts/model_assignment.json").exists() or (root/"metadata/model_assignment_commit.json").exists(): raise ValueError("unexpected_lifecycle_assignment_artifact")
    return {"decision":decision,"decisionCommit":decision_commit,"assignment":assignment,"assignmentCommit":assignment_commit}


def _assert_bundle_equal(actual: Mapping[str,Any], expected: Mapping[str,Any]) -> None:
    for key in ("decision","decisionCommit","assignment","assignmentCommit"):
        if actual.get(key) != expected.get(key): raise ValueError(f"independent_lifecycle_reconciliation_failed:{key}")


def _pointer(job: Mapping[str,Any], bundle_root: Path, assignment: Mapping[str,Any], decision_commit: Mapping[str,Any]) -> dict[str,Any]:
    decision_path=bundle_root/"artifacts/lifecycle_decision.json"; assignment_path=bundle_root/"artifacts/model_assignment.json"; decision_commit_path=bundle_root/"metadata/lifecycle_decision_commit.json"; assignment_commit_path=bundle_root/"metadata/model_assignment_commit.json"
    relative=f"model-lifecycle/{job['lifecycleDecisionId']}"
    return {"schemaVersion":"1.0","deploymentId":"dhaka_south","assignmentId":assignment["assignmentId"],"assignmentAction":assignment["assignmentAction"],"assignedModelId":"random_forest","modelFamily":"RandomForestRegressor","parameterSha256":PARAMETER_SHA,"featureOrderSha256":FEATURE_SHA,"candidateRegistrySha256":REGISTRY_SHA,"policyId":POLICY_ID,"policyVersion":"p2-v1","policySha256":POLICY_SHA256,"lifecycleDecisionId":job["lifecycleDecisionId"],"lifecycleDecisionCommitSha256":sha(decision_commit_path),"assignmentCommitSha256":sha(assignment_commit_path),"assignmentPath":f"{relative}/artifacts/model_assignment.json","assignmentSha256":sha(assignment_path),"lifecycleDecisionPath":f"{relative}/artifacts/lifecycle_decision.json","lifecycleDecisionSha256":sha(decision_path),"priorAssignmentId":assignment["priorAssignmentId"],"priorAssignmentCommitSha256":assignment["priorAssignmentCommitSha256"],"publishedAt":decision_commit["committedAt"],"activeModelAuthority":"committed_assignment","automaticAction":False}


def _publish_pointer(repository_root: Path, runtime_root: Path, job: Mapping[str,Any], bundle_root: Path, bundle: Mapping[str,Any], fail_for_test: bool=False) -> dict[str,Any]:
    pointer=_pointer(job,bundle_root,bundle["assignment"],bundle["decisionCommit"]); validate_schema(repository_root,"runtime_model_assignment_latest.schema.json",pointer)
    if fail_for_test: raise OSError("injected_assignment_pointer_publication_failure")
    latest=runtime_root/"deployments/dhaka_south/model-assignment/latest.json"; atomic_json(latest,pointer)
    if _json(latest)!=pointer: raise ValueError("assignment_pointer_reverification_failed")
    return pointer


def _fallback_from_decision(repository_root: Path, decision: Mapping[str,Any]) -> dict[str,Any]:
    if decision.get("activeAuthoritySourceBefore")!="historical_profile_fallback_pending_explicit_bootstrap" or decision.get("activeModelIdBefore")!="random_forest" or decision.get("activeModelFamilyBefore")!="RandomForestRegressor" or decision.get("activeParameterSha256Before")!=PARAMETER_SHA or decision.get("priorAssignmentId") is not None or decision.get("priorAssignmentCommitSha256") is not None or decision.get("profileSha256", PROFILE_SHA)!=PROFILE_SHA: raise ValueError("orphan_fallback_authority_invalid")
    profile_bytes=(repository_root/"config/deployments/dhaka_south/profile.json").read_bytes()
    expected=hashlib.sha256(b"historical_profile_fallback_pending_explicit_bootstrap\0"+profile_bytes+POLICY_SHA256.encode()).hexdigest()
    if decision.get("activeAuthoritySnapshotSha256Before")!=expected: raise ValueError("orphan_fallback_snapshot_invalid")
    return {"authoritySource":decision["activeAuthoritySourceBefore"],"authoritySnapshotSha256":expected,"assignmentPointerSha256":None,"assignmentId":None,"assignmentCommitSha256":None,"modelId":"random_forest","modelFamily":"RandomForestRegressor","parameterSha256":PARAMETER_SHA,"featureOrderSha256":FEATURE_SHA,"candidateRegistrySha256":REGISTRY_SHA,"quickPolicyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","quickPolicyVersion":"p1.4f-v1","quickPolicySha256":QUICK_SHA,"profileSha256":PROFILE_SHA}


def _verify_bootstrap_static(repository_root: Path) -> None:
    profile=repository_root/"config/deployments/dhaka_south/profile.json";registry=repository_root/"config/candidate_models.json";quick=repository_root/"config/deployments/dhaka_south/quick_forecast_policy.json"
    quick_value=_json(quick)
    if sha(profile)!=PROFILE_SHA or sha(registry)!=REGISTRY_SHA or quick_value.get("policy_sha256")!=QUICK_SHA or canonical_sha256(quick_value)!=QUICK_SHA or quick_value.get("feature_contract",{}).get("feature_order_sha256")!=FEATURE_SHA:
        raise ValueError("orphan_bootstrap_static_evidence_invalid")


def recover_committed_bundle(repository_root: Path, runtime_root: Path, job: Mapping[str,Any]) -> dict[str,Any] | None:
    committed=runtime_root/"model-lifecycle"/job["lifecycleDecisionId"]
    if not committed.exists(): return None
    load_model_lifecycle_policy(repository_root); assignment_expected=job["action"] in {"bootstrap_historical_profile","promote_selected_model","rollback_previous_assignment"}; actual=_load_bundle(repository_root,committed,assignment_expected)
    latest=runtime_root/"deployments/dhaka_south/model-assignment/latest.json"
    if assignment_expected and latest.is_file():
        pointer=_json(latest)
        if pointer.get("assignmentId")==actual["assignment"]["assignmentId"]:
            resolve_active_model(repository_root,runtime_root); return {"lifecycleDecisionId":job["lifecycleDecisionId"],"assignmentId":actual["assignment"]["assignmentId"],"idempotent":True,"recovered":False}
    fallback_orphan=assignment_expected and not latest.exists() and actual["decision"].get("activeAuthoritySourceBefore")=="historical_profile_fallback_pending_explicit_bootstrap"
    if fallback_orphan:
        _verify_bootstrap_static(repository_root)
        bundles=_assignment_bundles(runtime_root)
        if bundles != [committed]: raise ValueError("stale_orphan_assignment_history")
        active=_fallback_from_decision(repository_root,actual["decision"])
    else:
        active=resolve_active_model(repository_root,runtime_root,ignored_lifecycle_decision_id=job["lifecycleDecisionId"])
    verified=verify_action_sources(repository_root,runtime_root,job,active); expected=prepare_bundle(repository_root,runtime_root,job,active,verified); _assert_bundle_equal(actual,expected)
    if not assignment_expected: return {"lifecycleDecisionId":job["lifecycleDecisionId"],"assignmentId":None,"idempotent":True,"recovered":False}
    lock=runtime_root/"deployments/dhaka_south/model-assignment/locks/commit.lock"; lock.parent.mkdir(parents=True,exist_ok=True)
    try: descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc: raise ValueError("model_assignment_commit_locked") from exc
    try:
        state,digest=assignment_pointer_state(runtime_root)
        if (state,digest)!=(job["expectedAssignmentPointerState"],job.get("expectedAssignmentPointerSha256")): raise ValueError("stale_orphan_assignment_bundle")
        if fallback_orphan and _assignment_bundles(runtime_root)!=[committed]: raise ValueError("stale_orphan_assignment_history")
        verified_locked=verify_action_sources(repository_root,runtime_root,job,active); expected_locked=prepare_bundle(repository_root,runtime_root,job,active,verified_locked); _assert_bundle_equal(actual,expected_locked)
        protected=_protected_state(repository_root,runtime_root)
        _publish_pointer(repository_root,runtime_root,job,committed,actual); resolve_active_model(repository_root,runtime_root)
        if _protected_state(repository_root,runtime_root)!=protected: raise ValueError("unrelated_protected_state_modified")
        return {"lifecycleDecisionId":job["lifecycleDecisionId"],"assignmentId":actual["assignment"]["assignmentId"],"idempotent":True,"recovered":True}
    finally:
        os.close(descriptor); lock.unlink(missing_ok=True)


def commit_lifecycle(repository_root: Path, runtime_root: Path, job_path: Path, staging: Path, *, fail_pointer_publication_for_test: bool=False) -> dict[str,Any]:
    job=_json(job_path); validate_schema(repository_root,"runtime_job.schema.json",job); load_model_lifecycle_policy(repository_root)
    recovered=recover_committed_bundle(repository_root,runtime_root,job)
    if recovered is not None: return recovered
    verify_expected_pointer(job,runtime_root); active=resolve_active_model(repository_root,runtime_root); verified=verify_action_sources(repository_root,runtime_root,job,active); expected=prepare_bundle(repository_root,runtime_root,job,active,verified)
    actual=_load_bundle(repository_root,staging,expected["assignment"] is not None); _assert_bundle_equal(actual,expected); protected_before=_protected_state(repository_root,runtime_root)
    lock=runtime_root/"deployments/dhaka_south/model-assignment/locks/commit.lock"; lock.parent.mkdir(parents=True,exist_ok=True)
    try: descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc: raise ValueError("model_assignment_commit_locked") from exc
    committed=runtime_root/"model-lifecycle"/job["lifecycleDecisionId"]
    try:
        verify_expected_pointer(job,runtime_root); active_now=resolve_active_model(repository_root,runtime_root)
        if active_now["authoritySnapshotSha256"]!=active["authoritySnapshotSha256"]: raise ValueError("stale_active_model_authority")
        verified_now=verify_action_sources(repository_root,runtime_root,job,active_now); expected_now=prepare_bundle(repository_root,runtime_root,job,active_now,verified_now); _assert_bundle_equal(actual,expected_now)
        verify_expected_pointer(job,runtime_root); committed.parent.mkdir(parents=True,exist_ok=True); os.replace(staging,committed)
        committed_bundle=_load_bundle(repository_root,committed,expected["assignment"] is not None); _assert_bundle_equal(committed_bundle,expected_now)
        verified_publish=verify_action_sources(repository_root,runtime_root,job,active_now); expected_publish=prepare_bundle(repository_root,runtime_root,job,active_now,verified_publish); _assert_bundle_equal(committed_bundle,expected_publish); verify_expected_pointer(job,runtime_root)
        if _protected_state(repository_root,runtime_root)!=protected_before: raise ValueError("unrelated_protected_state_modified_before_pointer_publication")
        if committed_bundle["assignment"] is not None: _publish_pointer(repository_root,runtime_root,job,committed,committed_bundle,fail_pointer_publication_for_test)
        if _protected_state(repository_root,runtime_root)!=protected_before: raise ValueError("unrelated_protected_state_modified")
        if committed_bundle["assignment"] is not None: resolve_active_model(repository_root,runtime_root)
        return {"lifecycleDecisionId":job["lifecycleDecisionId"],"assignmentId":committed_bundle["assignment"] and committed_bundle["assignment"]["assignmentId"],"idempotent":False,"recovered":False}
    finally:
        os.close(descriptor); lock.unlink(missing_ok=True)
