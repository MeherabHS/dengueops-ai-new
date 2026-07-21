"""Independent lifecycle reconciliation, immutable publication, and orphan recovery."""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parent.parent

from feature_engineering import FEATURE_COLUMNS
from runtime_active_model import FEATURE_SHA, PARAMETER_SHA, PROFILE_SHA, QUICK_SHA, REGISTRY_SHA, resolve_active_model, resolve_active_model_p2_v2, resolve_historical_active_model_p2_v1
from runtime_commit import atomic_json, json_sha
from runtime_model_lifecycle import prepare_bundle, validate_schema, verify_action_sources, _extract_and_validate_policy_version
from runtime_model_lifecycle_policy import POLICY_ID, POLICY_SHA256, canonical_sha256, load_model_lifecycle_policy
from runtime_model_lifecycle_source import assignment_pointer_state, verify_expected_pointer



def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file(): raise ValueError("lifecycle_commit_artifact_missing_or_unsafe")
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError("lifecycle_commit_artifact_not_object")
    return value


def _tree_hash(path: Path) -> str:
    if not path.exists(): return "ABSENT"
    rows=[]
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()): rows.append(f"{item.relative_to(path).as_posix()}:{raw_sha256(item)}")
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()



def _feature_order_identity(repository_root: Path) -> str:
    computed = hashlib.sha256(json.dumps(list(FEATURE_COLUMNS), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    cr_path = repository_root / "config/candidate_models_p1.2a-v1.json"
    if not cr_path.exists():
        cr_path = repository_root / "config/candidate_models.json"
    registry = _json(cr_path)

    qp_path = repository_root / "config/deployments/dhaka_south/quick_forecast_policy_p1.4f-v1.json"
    if not qp_path.exists():
        qp_path = repository_root / "config/deployments/dhaka_south/quick_forecast_policy.json"
    quick = _json(qp_path)

    lp_path = repository_root / "config/deployments/dhaka_south/model_lifecycle_policy_p2-v1.json"
    if not lp_path.exists():
        lp_path = repository_root / "config/deployments/dhaka_south/model_lifecycle_policy.json"
    lifecycle = _json(lp_path)

    quick_fo = quick.get("feature_contract", {}).get("feature_order_sha256") or quick.get("featureOrderSha256")
    lifecycle_fo = lifecycle.get("feature_order_sha256") or lifecycle.get("featureOrderSha256")

    identities = (
        computed,
        FEATURE_SHA,
        registry.get("feature_order_sha256") or registry.get("featureOrderSha256"),
        quick_fo,
        lifecycle_fo,
    )
    if any(identity != FEATURE_SHA for identity in identities):
        raise ValueError("protected_feature_order_identity_invalid")
    return computed


def _protected_state(repository_root: Path, runtime_root: Path) -> dict[str, str]:
    qp_path = repository_root / "config/deployments/dhaka_south/quick_forecast_policy_p1.4f-v1.json"
    if not qp_path.exists():
        qp_path = repository_root / "config/deployments/dhaka_south/quick_forecast_policy.json"
    cr_path = repository_root / "config/candidate_models_p1.2a-v1.json"
    if not cr_path.exists():
        cr_path = repository_root / "config/candidate_models.json"
    paths = {
        "profile": repository_root / "config/deployments/dhaka_south/profile.json",
        "candidateRegistry": cr_path,
        "featureEngineering": repository_root / "analytics/feature_engineering.py",
        "quickPolicy": qp_path,
        "forecastLatest": runtime_root / "deployments/dhaka_south/latest.json",
        "monitoringLatest": runtime_root / "deployments/dhaka_south/monitoring/latest.json",
        "degradationLatest": runtime_root / "deployments/dhaka_south/degradation/latest.json"
    }
    result = {key: (sha(path) if path.is_file() else "ABSENT") for key, path in paths.items()}
    result["featureOrderIdentity"] = _feature_order_identity(repository_root)
    result["authorizationState"] = _tree_hash(runtime_root / "authorization-state")
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


def _assert_bundle_equal(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    if json_sha(actual["decision"]) != json_sha(expected["decision"]) or json_sha(actual["decisionCommit"]) != json_sha(expected["decisionCommit"]):
        raise ValueError("stale_lifecycle_decision_bundle")
    if (actual["assignment"] is None) != (expected["assignment"] is None):
        raise ValueError("stale_lifecycle_assignment_presence")
    if actual["assignment"] is not None and (json_sha(actual["assignment"]) != json_sha(expected["assignment"]) or json_sha(actual["assignmentCommit"]) != json_sha(expected["assignmentCommit"])):
        raise ValueError("stale_lifecycle_assignment_bundle")



def _pointer(job: Mapping[str, Any], bundle_root: Path, assignment: Mapping[str, Any], decision_commit: Mapping[str, Any]) -> dict[str, Any]:
    decision_path = bundle_root / "artifacts/lifecycle_decision.json"
    assignment_path = bundle_root / "artifacts/model_assignment.json"
    decision_commit_path = bundle_root / "metadata/lifecycle_decision_commit.json"
    assignment_commit_path = bundle_root / "metadata/model_assignment_commit.json"
    relative = f"model-lifecycle/{job['lifecycleDecisionId']}"
    return {
        "schemaVersion": "1.0",
        "deploymentId": "dhaka_south",
        "assignmentId": assignment["assignmentId"],
        "assignmentAction": assignment["assignmentAction"],
        "assignedModelId": "random_forest",
        "modelFamily": "RandomForestRegressor",
        "parameterSha256": PARAMETER_SHA,
        "featureOrderSha256": FEATURE_SHA,
        "candidateRegistrySha256": REGISTRY_SHA,
        "policyId": POLICY_ID,
        "policyVersion": "p2-v1",
        "policySha256": POLICY_SHA256,
        "lifecycleDecisionId": job["lifecycleDecisionId"],
        "lifecycleDecisionCommitSha256": sha(decision_commit_path),
        "assignmentCommitSha256": sha(assignment_commit_path),
        "assignmentPath": f"{relative}/artifacts/model_assignment.json",
        "assignmentSha256": sha(assignment_path),
        "lifecycleDecisionPath": f"{relative}/artifacts/lifecycle_decision.json",
        "lifecycleDecisionSha256": sha(decision_path),
        "priorAssignmentId": assignment["priorAssignmentId"],
        "priorAssignmentCommitSha256": assignment["priorAssignmentCommitSha256"],
        "publishedAt": decision_commit["committedAt"],
        "activeModelAuthority": "committed_assignment",
        "automaticAction": False,
    }



def _publish_pointer(repository_root: Path, runtime_root: Path, job: Mapping[str,Any], bundle_root: Path, bundle: Mapping[str,Any], fail_for_test: bool=False) -> dict[str,Any]:
    verify_expected_pointer(job,runtime_root); pointer=_pointer(job,bundle_root,bundle["assignment"],bundle["decisionCommit"]); validate_schema(repository_root,"runtime_model_assignment_latest.schema.json",pointer)
    if fail_for_test: raise OSError("injected_assignment_pointer_publication_failure")
    target=runtime_root/"deployments/dhaka_south/model-assignment/latest.json"; atomic_json(target,pointer)
    return pointer



def _fallback_from_decision(repository_root: Path, decision: Mapping[str,Any]) -> dict[str,Any]:
    profile_bytes=(repository_root/"config/deployments/dhaka_south/profile.json").read_bytes()
    snapshot=hashlib.sha256(b"historical_profile_fallback_pending_explicit_bootstrap\0"+profile_bytes+POLICY_SHA256.encode()).hexdigest()
    return {"authoritySource":"historical_profile_fallback_pending_explicit_bootstrap","authoritySnapshotSha256":snapshot,"assignmentPointerSha256":None,"assignmentId":None,"assignmentCommitSha256":None,"modelId":"random_forest","modelFamily":"RandomForestRegressor","parameterSha256":PARAMETER_SHA,"featureOrderSha256":FEATURE_SHA,"candidateRegistrySha256":REGISTRY_SHA,"quickPolicyId":"RUNTIME.QUICK_FORECAST.COMPATIBILITY","quickPolicyVersion":"p1.4f-v1","quickPolicySha256":QUICK_SHA,"lifecyclePolicyId":"RUNTIME.MODEL_LIFECYCLE.DECISION","lifecyclePolicyVersion":"p2-v1","lifecyclePolicySha256":POLICY_SHA256,"profileSha256":PROFILE_SHA,"bootstrapRequired":True,"quickForecastCompatible":True}


def _json_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file(): raise ValueError("lifecycle_commit_artifact_missing_or_unsafe")
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict): raise ValueError("lifecycle_commit_artifact_not_object")
    return value, raw


def canonical_json_sha256(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json_sha(value)
    if isinstance(value, Path):
        return hashlib.sha256(value.read_bytes()).hexdigest()
    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    return hashlib.sha256(str(value).encode()).hexdigest()


def _verify_bootstrap_static(repository_root: Path) -> None:
    profile_path = repository_root / "config/deployments/dhaka_south/profile.json"
    qp_path = repository_root / "config/deployments/dhaka_south/quick_forecast_policy_p1.4f-v1.json"
    if not qp_path.exists():
        qp_path = repository_root / "config/deployments/dhaka_south/quick_forecast_policy.json"
    cr_path = repository_root / "config/candidate_models_p1.2a-v1.json"
    if not cr_path.exists():
        cr_path = repository_root / "config/candidate_models.json"

    profile, profile_bytes = _json_bytes(profile_path)
    quick_value, _ = _json_bytes(qp_path)
    registry, registry_bytes = _json_bytes(cr_path)

    if canonical_json_sha256(profile_bytes) != PROFILE_SHA or canonical_json_sha256(registry_bytes) != REGISTRY_SHA or quick_value.get("policy_sha256") != QUICK_SHA or canonical_sha256(quick_value) != QUICK_SHA or quick_value.get("feature_contract", {}).get("feature_order_sha256") != FEATURE_SHA:
        raise ValueError("orphan_bootstrap_static_evidence_invalid")







def recover_committed_bundle(repository_root: Path, runtime_root: Path, job: Mapping[str,Any]) -> dict[str,Any] | None:
    committed=runtime_root/"model-lifecycle"/job["lifecycleDecisionId"]
    if not committed.exists(): return None
    policy_version = _extract_and_validate_policy_version(job)
    load_model_lifecycle_policy(policy_version=policy_version, repository_root=repository_root)
    assignment_expected=job["action"] in {"bootstrap_historical_profile","promote_selected_model","rollback_previous_assignment"}; actual=_load_bundle(repository_root,committed,assignment_expected)
    latest=runtime_root/"deployments/dhaka_south/model-assignment/latest.json"
    if assignment_expected and latest.is_file():
        pointer=_json(latest)
        if pointer.get("assignmentId")==actual["assignment"]["assignmentId"]:
            if policy_version == "p2-v1":
                resolve_historical_active_model_p2_v1(repository_root=repository_root, runtime_root=runtime_root)
            else:
                resolve_active_model_p2_v2(repository_root=repository_root, runtime_root=runtime_root)
            return {"lifecycleDecisionId":job["lifecycleDecisionId"],"assignmentId":actual["assignment"]["assignmentId"],"idempotent":True,"recovered":False}
    fallback_orphan=assignment_expected and not latest.exists() and actual["decision"].get("activeAuthoritySourceBefore")=="historical_profile_fallback_pending_explicit_bootstrap"
    if fallback_orphan:
        _verify_bootstrap_static(repository_root)
        bundles=_assignment_bundles(runtime_root)
        if bundles != [committed]: raise ValueError("stale_orphan_assignment_history")
        active=_fallback_from_decision(repository_root,actual["decision"])
    else:
        if policy_version == "p2-v1":
            active=resolve_historical_active_model_p2_v1(repository_root=repository_root, runtime_root=runtime_root, ignored_lifecycle_decision_id=job["lifecycleDecisionId"])
        else:
            active=resolve_active_model_p2_v2(repository_root=repository_root, runtime_root=runtime_root)
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
        _publish_pointer(repository_root,runtime_root,job,committed,actual)
        if policy_version == "p2-v1":
            resolve_historical_active_model_p2_v1(repository_root=repository_root, runtime_root=runtime_root)
        else:
            resolve_active_model_p2_v2(repository_root=repository_root, runtime_root=runtime_root)
        if _protected_state(repository_root,runtime_root)!=protected: raise ValueError("unrelated_protected_state_modified")
        return {"lifecycleDecisionId":job["lifecycleDecisionId"],"assignmentId":actual["assignment"]["assignmentId"],"idempotent":True,"recovered":True}
    finally:
        os.close(descriptor); lock.unlink(missing_ok=True)


def commit_lifecycle(repository_root: Path, runtime_root: Path, job_path: Path, staging: Path, *, fail_pointer_publication_for_test: bool=False) -> dict[str,Any]:
    job=_json(job_path); validate_schema(repository_root,"runtime_job.schema.json",job)
    policy_version = _extract_and_validate_policy_version(job)
    load_model_lifecycle_policy(policy_version=policy_version, repository_root=repository_root)
    recovered=recover_committed_bundle(repository_root,runtime_root,job)
    if recovered is not None: return recovered
    verify_expected_pointer(job,runtime_root)
    if policy_version == "p2-v1":
        active=resolve_historical_active_model_p2_v1(repository_root=repository_root, runtime_root=runtime_root)
    else:
        active=resolve_active_model_p2_v2(repository_root=repository_root, runtime_root=runtime_root)
    verified=verify_action_sources(repository_root,runtime_root,job,active); expected=prepare_bundle(repository_root,runtime_root,job,active,verified)
    actual=_load_bundle(repository_root,staging,expected["assignment"] is not None); _assert_bundle_equal(actual,expected); protected_before=_protected_state(repository_root,runtime_root)
    lock=runtime_root/"deployments/dhaka_south/model-assignment/locks/commit.lock"; lock.parent.mkdir(parents=True,exist_ok=True)
    try: descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError as exc: raise ValueError("model_assignment_commit_locked") from exc
    committed=runtime_root/"model-lifecycle"/job["lifecycleDecisionId"]
    try:
        verify_expected_pointer(job,runtime_root)
        if policy_version == "p2-v1":
            active_now=resolve_historical_active_model_p2_v1(repository_root=repository_root, runtime_root=runtime_root)
        else:
            active_now=resolve_active_model_p2_v2(repository_root=repository_root, runtime_root=runtime_root)
        if active_now["authoritySnapshotSha256"]!=active["authoritySnapshotSha256"]: raise ValueError("stale_active_model_authority")
        verified_now=verify_action_sources(repository_root,runtime_root,job,active_now); expected_now=prepare_bundle(repository_root,runtime_root,job,active_now,verified_now); _assert_bundle_equal(actual,expected_now)
        verify_expected_pointer(job,runtime_root); committed.parent.mkdir(parents=True,exist_ok=True); os.replace(staging,committed)
        committed_bundle=_load_bundle(repository_root,committed,expected["assignment"] is not None); _assert_bundle_equal(committed_bundle,expected_now)
        verified_publish=verify_action_sources(repository_root,runtime_root,job,active_now); expected_publish=prepare_bundle(repository_root,runtime_root,job,active_now,verified_publish); _assert_bundle_equal(committed_bundle,expected_publish); verify_expected_pointer(job,runtime_root)
        if _protected_state(repository_root,runtime_root)!=protected_before: raise ValueError("unrelated_protected_state_modified_before_pointer_publication")
        if committed_bundle["assignment"] is not None: _publish_pointer(repository_root,runtime_root,job,committed,committed_bundle,fail_pointer_publication_for_test)
        if _protected_state(repository_root,runtime_root)!=protected_before: raise ValueError("unrelated_protected_state_modified")
        if committed_bundle["assignment"] is not None:
            if policy_version == "p2-v1":
                resolve_historical_active_model_p2_v1(repository_root=repository_root, runtime_root=runtime_root)
            else:
                resolve_active_model_p2_v2(repository_root=repository_root, runtime_root=runtime_root)
        return {"lifecycleDecisionId":job["lifecycleDecisionId"],"assignmentId":committed_bundle["assignment"] and committed_bundle["assignment"]["assignmentId"],"idempotent":False,"recovered":False}
    finally:
        os.close(descriptor); lock.unlink(missing_ok=True)


def verify_p2_v2_evidence_chain(
    repository_root: Path,
    runtime_root: Path,
    one_run_forecast_run_id: str,
    reason: str,
    acknowledgement: bool
) -> dict[str, Any]:
    if not acknowledgement:
        raise ValueError("governance_acknowledgements_required")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason_required")

    run_dir = runtime_root / "runs" / one_run_forecast_run_id
    run_meta_path = run_dir / "metadata/run.json"
    if not run_meta_path.exists():
        raise ValueError(f"Forecast run metadata missing at {run_meta_path}")

    run_meta = json.loads(run_meta_path.read_text(encoding="utf-8"))
    decision_id = run_meta.get("decisionId")
    authorization_id = run_meta.get("authorizationId")
    assessment_id = run_meta.get("assessmentId")
    model_id = run_meta.get("selectedModelId") or run_meta.get("modelId")
    param_sha = run_meta.get("selectedModelParameterSha256") or run_meta.get("parameterSha256") or PARAMETER_SHA

    if not model_id:
        raise ValueError("Model ID missing in forecast run metadata.")

    forecast_output_path = run_dir / "artifacts/forecast_output.json"
    if forecast_output_path.exists():
        raw_output_sha = hashlib.sha256(forecast_output_path.read_bytes()).hexdigest()
        if run_meta.get("forecastOutputSha256") and run_meta.get("forecastOutputSha256") != raw_output_sha:
            raise ValueError("forecast_output_tampered")

    policy, policy_sha = load_model_lifecycle_policy(
        policy_version="p2-v2",
        repository_root=repository_root,
        deployment_id="dhaka_south"
    )

    decision_commit_sha = run_meta.get("decisionCommitSha256")
    if not decision_commit_sha and decision_id:
        dc_path = runtime_root / "decisions" / decision_id / "metadata/commit.json"
        if dc_path.exists():
            decision_commit_sha = hashlib.sha256(dc_path.read_bytes()).hexdigest()
    if not decision_commit_sha:
        decision_commit_sha = "0" * 64

    return {
        "run_meta": run_meta,
        "model_id": model_id,
        "param_sha": param_sha,
        "assessment_id": assessment_id,
        "decision_id": decision_id,
        "authorization_id": authorization_id,
        "policy": policy,
        "policy_sha": policy_sha,
        "decision_commit_sha": decision_commit_sha
    }


def _pointer_p2_v2(
    repository_root: Path,
    assignment_id: str,
    record: Mapping[str, Any],
    commit_sha: str,
    policy: Mapping[str, Any],
    policy_sha: str,
    decision_commit_sha: str,
    prior_assignment_id: str | None,
    prior_commit_sha: str | None,
    now_iso: str
) -> dict[str, Any]:
    pointer = {
        "schemaVersion": "2.0",
        "deploymentId": "dhaka_south",
        "assignmentId": assignment_id,
        "assignmentAction": "assign_selected_model",
        "assignedModelId": record["modelId"],
        "modelFamily": record["modelFamily"],
        "parameterSha256": record["parameterSha256"],
        "featureOrderSha256": record["featureOrderSha256"],
        "candidateRegistrySha256": record["candidateRegistrySha256"],
        "policyId": policy.get("policyId", "RUNTIME.MODEL_LIFECYCLE.DECISION"),
        "policyVersion": policy.get("policyVersion", "p2-v2"),
        "policySha256": policy_sha,
        "sourceDecisionId": record["sourceDecisionId"],
        "sourceDecisionCommitSha256": decision_commit_sha,
        "assignmentCommitSha256": commit_sha,
        "priorAssignmentId": prior_assignment_id,
        "priorAssignmentCommitSha256": prior_commit_sha,
        "publishedAt": now_iso,
        "activeModelAuthority": "committed_assignment",
        "automaticAction": False,
    }
    validate_schema(repository_root, "runtime_model_assignment_latest.schema.json", pointer)
    return pointer


def commit_lifecycle_action(
    runtime_root: Path,
    one_run_forecast_run_id: str,
    reason: str,
    operator_identifier: str = "governed-operator",
    acknowledgement: bool = True,
    repository_root: Path = ROOT
) -> dict[str, Any]:
    try:
        evidence = verify_p2_v2_evidence_chain(
            repository_root=repository_root,
            runtime_root=runtime_root,
            one_run_forecast_run_id=one_run_forecast_run_id,
            reason=reason,
            acknowledgement=acknowledgement
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    run_meta = evidence["run_meta"]
    model_id = evidence["model_id"]
    param_sha = evidence["param_sha"]
    assessment_id = evidence["assessment_id"]
    decision_id = evidence["decision_id"]
    authorization_id = evidence["authorization_id"]
    policy = evidence["policy"]
    policy_sha = evidence["policy_sha"]
    decision_commit_sha = evidence["decision_commit_sha"]

    pointer_path = runtime_root / "deployments/dhaka_south/model-assignment/latest.json"
    prior_assignment_id = None
    prior_commit_sha = None

    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        prior_assignment_id = pointer.get("assignmentId")
        prior_commit_sha = pointer.get("commitSha256") or pointer.get("assignmentCommitSha256")

    assignment_id = str(uuid.uuid4())
    assignment_dir = runtime_root / "model-assignments" / assignment_id
    artifacts_dir = assignment_dir / "artifacts"
    metadata_dir = assignment_dir / "metadata"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    record = {
        "schemaVersion": "2.0",
        "assignmentId": assignment_id,
        "deploymentId": "dhaka_south",
        "assignmentAction": "assign_selected_model",
        "modelId": model_id,
        "modelFamily": "RandomForestRegressor" if model_id == "random_forest" else model_id,
        "parameterSha256": param_sha,
        "preprocessingIdentity": f"p2-v2-{model_id}",
        "candidateRegistrySha256": policy.get("candidateRegistrySha256") or REGISTRY_SHA,
        "featureOrderSha256": policy.get("featureOrderSha256") or FEATURE_SHA,
        "foldPlanSha256": run_meta.get("foldPlanSha256") or "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "sourceAssessmentId": assessment_id,
        "sourceDecisionId": decision_id,
        "sourceAuthorizationId": authorization_id,
        "sourceApprovedForecastRunId": one_run_forecast_run_id,
        "priorAssignmentId": prior_assignment_id,
        "priorAssignmentCommitSha256": prior_commit_sha,
        "operatorIdentifier": operator_identifier,
        "reason": reason,
        "assignedAt": now_iso
    }

    record_path = artifacts_dir / "assignment_record.json"
    atomic_json(record_path, record)
    record_bytes = record_path.read_bytes()
    record_sha = hashlib.sha256(record_bytes).hexdigest()

    commit = {
        "schemaVersion": "2.0",
        "assignmentId": assignment_id,
        "assignmentRecordSha256": record_sha,
        "committedAt": now_iso
    }

    commit_path = metadata_dir / "commit.json"
    atomic_json(commit_path, commit)
    commit_bytes = commit_path.read_bytes()
    commit_sha = hashlib.sha256(commit_bytes).hexdigest()

    new_pointer = _pointer_p2_v2(
        repository_root=repository_root,
        assignment_id=assignment_id,
        record=record,
        commit_sha=commit_sha,
        policy=policy,
        policy_sha=policy_sha,
        decision_commit_sha=decision_commit_sha,
        prior_assignment_id=prior_assignment_id,
        prior_commit_sha=prior_commit_sha,
        now_iso=now_iso
    )

    pointer_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(pointer_path, new_pointer)

    return {
        "success": True,
        "action": "assign_selected_model",
        "modelId": model_id,
        "assignmentId": assignment_id
    }
