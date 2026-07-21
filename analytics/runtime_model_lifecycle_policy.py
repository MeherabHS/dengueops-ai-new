"""Pure Product-v2 Phase B4 Model Lifecycle policy loader and validator."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, Mapping

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
POLICY_SCHEMA_PATH = ROOT / "config" / "runtime_model_lifecycle_policy.schema.json"
POLICY_ID = "RUNTIME.MODEL_LIFECYCLE.DECISION"
POLICY_VERSION = "p2-v1"
POLICY_SHA256 = "570a931bc2e98ca5cada78c5fe891e699e43e7c9f513b8df2257c06f1261b7bb"


class ModelLifecyclePolicyError(ValueError):
    """Raised when lifecycle policy bytes or identity bindings are invalid."""


LifecyclePolicyError = ModelLifecyclePolicyError


def canonical_sha256(policy: Mapping[str, Any]) -> str:
    content = dict(policy)
    content.pop("policy_sha256", None)
    content.pop("policySha256", None)
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


canonical_policy_sha256 = canonical_sha256


def load_model_lifecycle_policy_by_identity(
    *,
    policy_id: str,
    policy_version: str,
    expected_canonical_sha256: str,
    expected_raw_sha256: str | None = None,
    repository_root: Path = ROOT,
    deployment_id: str = "dhaka_south"
) -> tuple[dict[str, Any], str]:
    if policy_id != POLICY_ID:
        raise ModelLifecyclePolicyError(f"Unsupported policy_id '{policy_id}'.")

    if policy_version == "p2-v1":
        file_path = repository_root / "config" / "deployments" / deployment_id / "model_lifecycle_policy_p2-v1.json"
    elif policy_version == "p2-v2":
        file_path = repository_root / "config" / "deployments" / deployment_id / "model_lifecycle_policy.json"
    else:
        raise ModelLifecyclePolicyError(f"Unknown or unsupported policy version '{policy_version}'.")

    if not file_path.exists():
        raise ModelLifecyclePolicyError(f"Model lifecycle policy file not found: {file_path}")

    raw_bytes = file_path.read_bytes()
    if expected_raw_sha256 is not None:
        computed_raw = hashlib.sha256(raw_bytes).hexdigest()
        if computed_raw != expected_raw_sha256:
            raise ModelLifecyclePolicyError(f"Raw policy SHA-256 mismatch: expected {expected_raw_sha256}, got {computed_raw}.")

    try:
        policy = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelLifecyclePolicyError("Model lifecycle policy is not valid UTF-8 JSON.") from exc

    if not isinstance(policy, dict):
        raise ModelLifecyclePolicyError("Model lifecycle policy must be a JSON object.")

    decl_id = policy.get("policy_id") or policy.get("policyId")
    decl_ver = policy.get("policy_version") or policy.get("policyVersion")
    decl_hash = policy.get("policy_sha256") or policy.get("policySha256")

    if decl_id != policy_id or decl_ver != policy_version:
        raise ModelLifecyclePolicyError("Declared policy identity mismatch.")

    computed_canonical = canonical_sha256(policy)
    if decl_hash != computed_canonical:
        raise ModelLifecyclePolicyError(f"Embedded canonical policy hash mismatch: declared {decl_hash}, recomputed {computed_canonical}.")

    if computed_canonical != expected_canonical_sha256:
        raise ModelLifecyclePolicyError(f"Expected canonical policy hash mismatch: expected {expected_canonical_sha256}, got {computed_canonical}.")

    if policy_version == "p2-v2":
        schema_path = repository_root / "config" / "runtime_model_lifecycle_policy.schema.json"
        if schema_path.exists():
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema, format_checker=FormatChecker())
            errors = sorted(err.message for err in validator.iter_errors(policy))
            if errors:
                raise ModelLifecyclePolicyError(f"Schema validation failed: {'; '.join(errors)}")
    elif policy_version == "p2-v1":
        forbidden = ("automaticPromotionAllowed", "automaticRollbackAllowed", "automaticRetentionAllowed", "thresholdBasedActionAllowed", "arbitraryModelSelectionAllowed", "arbitraryRollbackTargetAllowed", "baselineAssignmentAllowed", "profileMutationAllowed", "unknownIdentityFallbackAllowed", "materialWorseningClassificationRequired", "lifecycleRecommendationFromDegradationEvidenceAllowed", "nonRandomForestActivationAllowed", "assignmentHistoryMutationAllowed")
        if any(policy.get(key) is not False for key in forbidden) or policy.get("operatorDecisionRequired") is not True or policy.get("activeQuickForecastPolicyRequired") is not True:
            raise ModelLifecyclePolicyError("Automatic, arbitrary, or non-Random-Forest lifecycle action is prohibited.")

    return policy, computed_canonical


def load_model_lifecycle_policy(
    *,
    policy_version: Literal["p2-v1", "p2-v2"],
    repository_root: Path = ROOT,
    deployment_id: str = "dhaka_south"
) -> tuple[dict[str, Any], str]:
    if policy_version == "p2-v1":
        expected_hash = POLICY_SHA256
    elif policy_version == "p2-v2":
        path = repository_root / "config" / "deployments" / deployment_id / "model_lifecycle_policy.json"
        if not path.exists():
            raise ModelLifecyclePolicyError("Model lifecycle policy file not found.")
        raw = json.loads(path.read_text(encoding="utf-8"))
        expected_hash = canonical_sha256(raw)
    else:
        raise ModelLifecyclePolicyError(f"Unknown or unsupported policy version '{policy_version}'.")

    return load_model_lifecycle_policy_by_identity(
        policy_id=POLICY_ID,
        policy_version=policy_version,
        expected_canonical_sha256=expected_hash,
        repository_root=repository_root,
        deployment_id=deployment_id
    )


def load_current_model_lifecycle_policy(
    repository_root: Path = ROOT,
    deployment_id: str = "dhaka_south"
) -> tuple[dict[str, Any], str]:
    return load_model_lifecycle_policy(
        policy_version="p2-v2",
        repository_root=repository_root,
        deployment_id=deployment_id
    )


load_and_validate_lifecycle_policy = load_current_model_lifecycle_policy
