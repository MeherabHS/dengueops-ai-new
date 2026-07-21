"""Resolve the active model from a verified assignment or the exact historical profile."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from runtime_model_lifecycle_policy import POLICY_SHA256, canonical_sha256, load_model_lifecycle_policy

PROFILE_SHA = "53fe1fb09aea994c34a5b3d6839b60092c777030445b8ec46c32520675a7233a"
REGISTRY_SHA = "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4"
FEATURE_SHA = "aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85"
QUICK_SHA = "5e6bcb68e5f29a50f8d377892d7786cc1932b3435e8a0b709a363d6c2e42bb9a"
PARAMETER_SHA = "ac37d2d2947de2f6004d39ecdfa3290c5d65901b796f1eb1fd248ad658e1b1e0"


class ActiveModelError(ValueError):
    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code or message


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_reparse_link(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _json_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    if _is_reparse_link(path) or not path.is_file():
        raise ActiveModelError("Active-model evidence is missing or unsafe.")
    data = path.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ActiveModelError("Active-model evidence must be an object.")
    return value, data


def _within(root: Path, candidate: Path) -> Path:
    root = root.resolve()
    lexical = Path(os.path.abspath(candidate))
    if lexical != root and root not in lexical.parents:
        raise ActiveModelError("Assignment path escaped the runtime root.")
    relative = lexical.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and _is_reparse_link(current):
            raise ActiveModelError("Assignment path contains a symbolic link.")
    resolved = lexical.resolve(strict=False)
    if resolved != root and root not in resolved.parents:
        raise ActiveModelError("Assignment path escaped the runtime root.")
    return lexical


def _schema(repository_root: Path, value: dict[str, Any], name: str) -> None:
    definition = json.loads((repository_root / "config" / name).read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(definition, format_checker=FormatChecker()).iter_errors(value), key=lambda item:list(item.path))
    if errors:
        raise ActiveModelError(f"Active-model evidence failed {name}: {errors[0].message}")


def _verify_static(repository_root: Path, policy: dict[str, Any], is_p2_v1: bool = True) -> None:
    profile, profile_bytes = _json_bytes(repository_root / "config/deployments/dhaka_south/profile.json")
    qp_archive = repository_root / "config/deployments/dhaka_south/quick_forecast_policy_p1.4f-v1.json"
    qp_primary = repository_root / "config/deployments/dhaka_south/quick_forecast_policy.json"

    if is_p2_v1 and qp_archive.exists():
        quick, _ = _json_bytes(qp_archive)
    elif qp_primary.exists():
        quick_p, _ = _json_bytes(qp_primary)
        p_version = quick_p.get("policy_version") or quick_p.get("policyVersion")
        p_sha = quick_p.get("policy_sha256") or quick_p.get("policySha256")
        if p_version == "p1.4f-v1" or p_sha == QUICK_SHA:
            if canonical_sha256(quick_p) != QUICK_SHA:
                raise ActiveModelError("Governed profile, registry, or Quick policy changed.")
            quick = quick_p
        elif qp_archive.exists():
            quick, _ = _json_bytes(qp_archive)
        else:
            quick = quick_p
    elif qp_archive.exists():
        quick, _ = _json_bytes(qp_archive)
    else:
        raise ActiveModelError("Quick forecast policy missing.")


    cr_primary = repository_root / "config/candidate_models.json"
    cr_archive = repository_root / "config/candidate_models_p1.2a-v1.json"
    if cr_archive.exists():
        _, registry_bytes = _json_bytes(cr_archive)
    else:
        _, registry_bytes = _json_bytes(cr_primary)

    quick_sha = canonical_sha256(quick)
    model = profile.get("model", {})
    if _sha(profile_bytes) != PROFILE_SHA or _sha(registry_bytes) != REGISTRY_SHA or quick_sha != QUICK_SHA:
        raise ActiveModelError("Governed profile, registry, or Quick policy changed.")
    if (model.get("model_id"), model.get("model_family"), model.get("model_parameters_sha256")) != ("random_forest", "RandomForestRegressor", PARAMETER_SHA):
        raise ActiveModelError("Historical profile model identity is invalid.")
    quick_fo = quick.get("feature_contract", {}).get("feature_order_sha256") or quick.get("featureOrderSha256")
    policy_fo = policy.get("feature_order_sha256") or policy.get("featureOrderSha256")
    if quick_fo != FEATURE_SHA or policy_fo != FEATURE_SHA:
        raise ActiveModelError("Feature-order identity is invalid.")


def _verify_bundle(repository_root: Path, runtime_root: Path, bundle: Path) -> dict[str,Any]:
    bundle=_within(runtime_root,bundle)
    if _is_reparse_link(bundle) or not bundle.is_dir(): raise ActiveModelError("Lifecycle bundle is unsafe.")
    decision,decision_bytes=_json_bytes(bundle/"artifacts/lifecycle_decision.json")
    decision_commit,decision_commit_bytes=_json_bytes(bundle/"metadata/lifecycle_decision_commit.json")
    _schema(repository_root,decision,"runtime_model_lifecycle_decision.schema.json");_schema(repository_root,decision_commit,"runtime_model_lifecycle_decision_commit.schema.json")
    lifecycle_id=decision.get("lifecycleDecisionId")
    if bundle.name!=lifecycle_id or decision_commit.get("lifecycleDecisionId")!=lifecycle_id or decision_commit.get("jobId")!=decision.get("jobId") or decision_commit.get("action")!=decision.get("action") or decision_commit.get("lifecycleDecisionSha256")!=_sha(decision_bytes): raise ActiveModelError("Lifecycle decision identity reconciliation failed.")
    if (decision.get("policyId"),decision.get("policyVersion"),decision.get("policySha256"))!=("RUNTIME.MODEL_LIFECYCLE.DECISION","p2-v1",POLICY_SHA256) or (decision_commit.get("policyId"),decision_commit.get("policyVersion"),decision_commit.get("policySha256"))!=("RUNTIME.MODEL_LIFECYCLE.DECISION","p2-v1",POLICY_SHA256): raise ActiveModelError("Lifecycle policy identity mismatch.")
    assignment_path=bundle/"artifacts/model_assignment.json"; assignment_commit_path=bundle/"metadata/model_assignment_commit.json"
    if not assignment_path.exists() and not assignment_commit_path.exists():
        if decision.get("resultingAssignmentId") is not None: raise ActiveModelError("Lifecycle decision assignment is missing.")
        return {"decision":decision,"decisionBytes":decision_bytes,"decisionCommit":decision_commit,"decisionCommitBytes":decision_commit_bytes,"assignment":None}
    if not assignment_path.is_file() or not assignment_commit_path.is_file(): raise ActiveModelError("Lifecycle assignment bundle is incomplete.")
    assignment,assignment_bytes=_json_bytes(assignment_path);assignment_commit,assignment_commit_bytes=_json_bytes(assignment_commit_path)
    _schema(repository_root,assignment,"runtime_model_assignment.schema.json");_schema(repository_root,assignment_commit,"runtime_model_assignment_commit.schema.json")
    mapping={"bootstrap":"bootstrap_historical_profile","promote":"promote_selected_model","rollback":"rollback_previous_assignment"}
    assignment_id=assignment.get("assignmentId"); action=assignment.get("assignmentAction")
    if decision.get("action")!=mapping.get(action) or decision.get("resultingAssignmentId")!=assignment_id or assignment_commit.get("assignmentId")!=assignment_id or assignment_commit.get("assignmentAction")!=action: raise ActiveModelError("Assignment action identity reconciliation failed.")
    if assignment.get("lifecycleDecisionId")!=lifecycle_id or assignment_commit.get("lifecycleDecisionId")!=lifecycle_id or assignment.get("lifecycleDecisionCommitSha256")!=_sha(decision_commit_bytes) or assignment_commit.get("lifecycleDecisionCommitSha256")!=_sha(decision_commit_bytes) or assignment_commit.get("assignmentSha256")!=_sha(assignment_bytes): raise ActiveModelError("Assignment commit reconciliation failed.")
    return {"decision":decision,"decisionBytes":decision_bytes,"decisionCommit":decision_commit,"decisionCommitBytes":decision_commit_bytes,"assignment":assignment,"assignmentBytes":assignment_bytes,"assignmentCommit":assignment_commit,"assignmentCommitBytes":assignment_commit_bytes,"bundle":bundle}


def _history(repository_root: Path, runtime_root: Path, ignored_lifecycle_decision_id: str | None = None) -> tuple[dict[str,dict[str,Any]],dict[str,dict[str,Any]]]:
    root=runtime_root/"model-lifecycle"; assignments={}; decisions={}
    if not root.exists(): return assignments,decisions
    _within(runtime_root,root)
    if _is_reparse_link(root) or not root.is_dir(): raise ActiveModelError("Lifecycle history is unsafe.")
    for bundle in root.iterdir():
        if _is_reparse_link(bundle) or not bundle.is_dir(): raise ActiveModelError("Lifecycle history contains an unsafe entry.")
        if bundle.name==ignored_lifecycle_decision_id: continue
        value=_verify_bundle(repository_root,runtime_root,bundle); decision_id=str(value["decision"]["lifecycleDecisionId"])
        if decision_id in decisions: raise ActiveModelError("Duplicate lifecycle decision identity exists.")
        decisions[decision_id]=value
        if value["assignment"] is not None:
            assignment_id=str(value["assignment"]["assignmentId"])
            if assignment_id in assignments: raise ActiveModelError("Duplicate assignment identity exists.")
            assignments[assignment_id]=value
    return assignments,decisions


def resolve_active_model_p2_v2(
    *,
    repository_root: Path = Path("."),
    runtime_root: Path,
    deployment_id: str = "dhaka_south"
) -> dict[str, Any]:
    policy, policy_sha = load_model_lifecycle_policy(
        policy_version="p2-v2",
        repository_root=repository_root,
        deployment_id=deployment_id
    )

    pointer_path = runtime_root / "deployments" / deployment_id / "model-assignment/latest.json"
    if not pointer_path.exists():
        raise ActiveModelError("active_model_not_assigned")

    pointer, pointer_bytes = _json_bytes(pointer_path)

    # 1. Complete schema validation before individual fields are consumed
    _schema(repository_root, pointer, "runtime_model_assignment_latest.schema.json")

    # 2. Schema and policy version checks
    if pointer.get("schemaVersion") != "2.0":
        raise ActiveModelError("Invalid pointer schema version for p2-v2 lifecycle.")
    if pointer.get("policyVersion") != "p2-v2":
        raise ActiveModelError("Invalid pointer policy version for p2-v2 lifecycle.")

    # 3. Check half-null prior assignment pair
    prior_id = pointer.get("priorAssignmentId")
    prior_sha = pointer.get("priorAssignmentCommitSha256")
    if (prior_id is None) != (prior_sha is None):
        raise ActiveModelError("Half-null prior assignment pair in pointer.")

    # 4. Assignment ID validation and directory path safety
    assignment_id = pointer.get("assignmentId")
    if not assignment_id or "/" in str(assignment_id) or "\\" in str(assignment_id) or ".." in str(assignment_id):
        raise ActiveModelError("Invalid assignmentId in pointer.")

    if "assignmentPath" in pointer and "model-lifecycle" in str(pointer.get("assignmentPath")):
        raise ActiveModelError("p2-v2 pointer cannot reference model-lifecycle directory.")

    assignment_dir = runtime_root / "model-assignments" / str(assignment_id)
    _within(runtime_root, assignment_dir)

    record_path = assignment_dir / "artifacts/assignment_record.json"
    commit_path = assignment_dir / "metadata/commit.json"
    if not record_path.exists() or not commit_path.exists():
        raise ActiveModelError("Assignment record or commit missing.")

    record, record_bytes = _json_bytes(record_path)
    commit, commit_bytes = _json_bytes(commit_path)

    # 5. Reconcile pointer, assignment record, and commit
    if pointer.get("assignedModelId") != record.get("modelId"):
        raise ActiveModelError("Pointer assignedModelId mismatch against assignment record modelId.")

    actual_commit_sha = _sha(commit_bytes)
    pointer_commit_sha = pointer.get("assignmentCommitSha256") or pointer.get("commitSha256")
    if pointer_commit_sha != actual_commit_sha:
        raise ActiveModelError("Pointer commit hash mismatch.")

    if pointer.get("assignmentId") != record.get("assignmentId"):
        raise ActiveModelError("Pointer assignmentId mismatch against assignment record.")

    if pointer.get("priorAssignmentId") != record.get("priorAssignmentId"):
        raise ActiveModelError("Pointer priorAssignmentId mismatch against assignment record.")

    if pointer.get("priorAssignmentCommitSha256") != record.get("priorAssignmentCommitSha256"):
        raise ActiveModelError("Pointer priorAssignmentCommitSha256 mismatch against assignment record.")

    if _sha(record_bytes) != commit.get("assignmentRecordSha256"):
        raise ActiveModelError("Assignment record hash mismatch against commit.")

    # 6. Assignment chain verification
    seen = {str(assignment_id)}
    current = record
    while current.get("priorAssignmentId"):
        curr_prior_id = str(current["priorAssignmentId"])
        curr_prior_sha = current.get("priorAssignmentCommitSha256")
        if not curr_prior_sha:
            raise ActiveModelError("Prior assignment commit SHA missing in chain.")
        if curr_prior_id in seen or "/" in curr_prior_id or "\\" in curr_prior_id or ".." in curr_prior_id:
            raise ActiveModelError("Assignment chain cycle or invalid prior ID detected.")
        seen.add(curr_prior_id)
        prior_dir = runtime_root / "model-assignments" / curr_prior_id
        _within(runtime_root, prior_dir)
        if not prior_dir.exists() or not (prior_dir / "metadata/commit.json").exists():
            raise ActiveModelError("Prior assignment missing or corrupt.")
        if _sha((prior_dir / "metadata/commit.json").read_bytes()) != curr_prior_sha:
            raise ActiveModelError("Prior assignment commit hash mismatch.")
        current = json.loads((prior_dir / "artifacts/assignment_record.json").read_text(encoding="utf-8"))

    return {
        "authoritySource": "committed_assignment",
        "assignmentId": str(assignment_id),
        "modelId": record["modelId"],
        "modelFamily": record["modelFamily"],
        "parameterSha256": record["parameterSha256"],
        "preprocessingIdentity": record["preprocessingIdentity"],
        "candidateRegistrySha256": record["candidateRegistrySha256"],
        "featureOrderSha256": record["featureOrderSha256"],
        "foldPlanSha256": record["foldPlanSha256"],
        "sourceAssessmentId": record["sourceAssessmentId"],
        "sourceDecisionId": record["sourceDecisionId"],
        "sourceAuthorizationId": record["sourceAuthorizationId"],
        "sourceApprovedForecastRunId": record["sourceApprovedForecastRunId"],
        "policyId": policy["policyId"],
        "policyVersion": policy["policyVersion"],
        "policySha256": policy_sha,
        "assignedAt": record["assignedAt"],
        "deploymentModelAdopted": True
    }


def resolve_historical_active_model_p2_v1(
    *,
    repository_root: Path = Path("."),
    runtime_root: Path,
    deployment_id: str = "dhaka_south",
    ignored_lifecycle_decision_id: str | None = None
) -> dict[str, Any]:
    policy, policy_sha = load_model_lifecycle_policy(
        policy_version="p2-v1",
        repository_root=repository_root,
        deployment_id=deployment_id
    )
    _verify_static(repository_root, policy, is_p2_v1=True)

    assignment_root = runtime_root / "deployments" / deployment_id / "model-assignment"
    latest_path = assignment_root / "latest.json"
    assignments, decisions = _history(repository_root, runtime_root, ignored_lifecycle_decision_id)

    if not latest_path.exists():
        if assignments:
            raise ActiveModelError("Assignment history exists without an active pointer.")
        profile_bytes = (repository_root / "config/deployments/dhaka_south/profile.json").read_bytes()
        snapshot = _sha(b"historical_profile_fallback_pending_explicit_bootstrap\0" + profile_bytes + POLICY_SHA256.encode())
        return {
            "authoritySource": "historical_profile_fallback_pending_explicit_bootstrap",
            "authoritySnapshotSha256": snapshot,
            "assignmentPointerSha256": None,
            "assignmentId": None,
            "assignmentCommitSha256": None,
            "modelId": "random_forest",
            "modelFamily": "RandomForestRegressor",
            "parameterSha256": PARAMETER_SHA,
            "featureOrderSha256": FEATURE_SHA,
            "candidateRegistrySha256": REGISTRY_SHA,
            "quickPolicyId": "RUNTIME.QUICK_FORECAST.COMPATIBILITY",
            "quickPolicyVersion": "p1.4f-v1",
            "quickPolicySha256": QUICK_SHA,
            "lifecyclePolicyId": "RUNTIME.MODEL_LIFECYCLE.DECISION",
            "lifecyclePolicyVersion": "p2-v1",
            "lifecyclePolicySha256": POLICY_SHA256,
            "profileSha256": PROFILE_SHA,
            "bootstrapRequired": True,
            "quickForecastCompatible": True
        }

    pointer, pointer_bytes = _json_bytes(latest_path)
    if pointer.get("schemaVersion") == "2.0" or (runtime_root / "model-assignments" / str(pointer.get("assignmentId"))).exists():
        raise ActiveModelError("Cross-version assignment pointer rejected by historical p2-v1 resolver.")

    _schema(repository_root, pointer, "runtime_model_assignment_latest.schema.json")
    if pointer.get("policySha256") != POLICY_SHA256 or pointer.get("activeModelAuthority") != "committed_assignment":
        raise ActiveModelError("Assignment pointer identity is invalid.")

    expected_assignment_path = f"model-lifecycle/{pointer['lifecycleDecisionId']}/artifacts/model_assignment.json"
    expected_decision_path = f"model-lifecycle/{pointer['lifecycleDecisionId']}/artifacts/lifecycle_decision.json"
    if pointer.get("assignmentPath") != expected_assignment_path or pointer.get("lifecycleDecisionPath") != expected_decision_path:
        raise ActiveModelError("Assignment artifact path identity is invalid.")

    _within(runtime_root, runtime_root / pointer["assignmentPath"])
    _within(runtime_root, runtime_root / pointer["lifecycleDecisionPath"])
    bundle = decisions.get(str(pointer.get("lifecycleDecisionId")))
    assignment_bundle = assignments.get(str(pointer.get("assignmentId")))
    if bundle is None or bundle is not assignment_bundle:
        raise ActiveModelError("Assignment pointer does not identify one verified bundle.")

    assignment = bundle["assignment"]
    assignment_bytes = bundle["assignmentBytes"]
    assignment_commit = bundle["assignmentCommit"]
    assignment_commit_bytes = bundle["assignmentCommitBytes"]
    decision = bundle["decision"]
    decision_bytes = bundle["decisionBytes"]
    decision_commit = bundle["decisionCommit"]
    decision_commit_bytes = bundle["decisionCommitBytes"]

    if (_sha(assignment_bytes), _sha(decision_bytes), _sha(assignment_commit_bytes), _sha(decision_commit_bytes)) != (pointer["assignmentSha256"], pointer["lifecycleDecisionSha256"], pointer["assignmentCommitSha256"], pointer["lifecycleDecisionCommitSha256"]):
        raise ActiveModelError("Assignment artifact hash mismatch.")
    if assignment.get("assignmentId") != pointer.get("assignmentId") or assignment_commit.get("assignmentId") != pointer.get("assignmentId") or decision.get("lifecycleDecisionId") != pointer.get("lifecycleDecisionId") or decision_commit.get("lifecycleDecisionId") != pointer.get("lifecycleDecisionId"):
        raise ActiveModelError("Assignment identity reconciliation failed.")
    if assignment.get("lifecycleDecisionCommitSha256") != pointer.get("lifecycleDecisionCommitSha256") or assignment_commit.get("lifecycleDecisionCommitSha256") != pointer.get("lifecycleDecisionCommitSha256") or assignment_commit.get("assignmentSha256") != _sha(assignment_bytes) or decision_commit.get("lifecycleDecisionSha256") != _sha(decision_bytes):
        raise ActiveModelError("Assignment commit reconciliation failed.")

    pointer_identity = (pointer.get("assignedModelId"), pointer.get("modelFamily"), pointer.get("parameterSha256"), pointer.get("featureOrderSha256"), pointer.get("candidateRegistrySha256"), pointer.get("assignmentAction"), pointer.get("priorAssignmentId"), pointer.get("priorAssignmentCommitSha256"))
    assignment_identity = (assignment.get("assignedModelId"), assignment.get("modelFamily"), assignment.get("parameterSha256"), assignment.get("featureOrderSha256"), assignment.get("candidateRegistrySha256"), assignment.get("assignmentAction"), assignment.get("priorAssignmentId"), assignment.get("priorAssignmentCommitSha256"))
    if pointer_identity != assignment_identity:
        raise ActiveModelError("Assignment pointer model identity mismatch.")

    seen: set[str] = {str(assignment["assignmentId"])}
    current = assignment
    while current.get("priorAssignmentId") is not None:
        prior_id = str(current["priorAssignmentId"])
        if prior_id in seen:
            raise ActiveModelError("Assignment chain contains a cycle.")
        seen.add(prior_id)
        prior = assignments.get(prior_id)
        if prior is None:
            raise ActiveModelError("Prior assignment cannot be verified.")
        if _sha(prior["assignmentCommitBytes"]) != current.get("priorAssignmentCommitSha256") or prior["assignmentCommit"].get("assignmentSha256") != _sha(prior["assignmentBytes"]) or prior["decisionCommit"].get("lifecycleDecisionSha256") != _sha(prior["decisionBytes"]) or prior["assignment"].get("lifecycleDecisionCommitSha256") != _sha(prior["decisionCommitBytes"]):
            raise ActiveModelError("Prior assignment commit hash mismatch.")
        current = prior["assignment"]

    if seen != set(assignments):
        raise ActiveModelError("Assignment history contains an orphan or later bundle.")

    return {
        "authoritySource": "committed_assignment",
        "authoritySnapshotSha256": _sha(pointer_bytes),
        "assignmentPointerSha256": _sha(pointer_bytes),
        "assignmentId": pointer["assignmentId"],
        "assignmentCommitSha256": pointer["assignmentCommitSha256"],
        "assignmentAction": pointer["assignmentAction"],
        "effectiveAt": pointer["publishedAt"],
        "priorAssignmentId": pointer["priorAssignmentId"],
        "modelId": "random_forest",
        "modelFamily": "RandomForestRegressor",
        "parameterSha256": PARAMETER_SHA,
        "featureOrderSha256": FEATURE_SHA,
        "candidateRegistrySha256": REGISTRY_SHA,
        "quickPolicyId": "RUNTIME.QUICK_FORECAST.COMPATIBILITY",
        "quickPolicyVersion": "p1.4f-v1",
        "quickPolicySha256": QUICK_SHA,
        "lifecyclePolicyId": "RUNTIME.MODEL_LIFECYCLE.DECISION",
        "lifecyclePolicyVersion": "p2-v1",
        "lifecyclePolicySha256": POLICY_SHA256,
        "profileSha256": None,
        "bootstrapRequired": False,
        "quickForecastCompatible": True
    }


def resolve_active_model(
    repository_root: Path = Path("."),
    runtime_root: Path = None, # type: ignore
    deployment_id: str = "dhaka_south"
) -> dict[str, Any]:
    """Public active model resolution entry point routing between p2-v2 and p2-v1 based on pointer identity or fallback."""
    if runtime_root is None:
        raise ValueError("runtime_root is required.")

    pointer_path = runtime_root / "deployments" / deployment_id / "model-assignment/latest.json"
    if pointer_path.exists():
        try:
            pointer, _ = _json_bytes(pointer_path)
            if pointer.get("schemaVersion") == "1.0":
                return resolve_historical_active_model_p2_v1(
                    repository_root=repository_root,
                    runtime_root=runtime_root,
                    deployment_id=deployment_id,
                )
        except Exception:
            pass
        return resolve_active_model_p2_v2(
            repository_root=repository_root,
            runtime_root=runtime_root,
            deployment_id=deployment_id,
        )

    return resolve_historical_active_model_p2_v1(
        repository_root=repository_root,
        runtime_root=runtime_root,
        deployment_id=deployment_id,
    )
