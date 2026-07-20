"""Fail-closed loader for the first human-governed model lifecycle policy."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker
from runtime_context import ROOT

POLICY_ID = "RUNTIME.MODEL_LIFECYCLE.DECISION"
POLICY_VERSION = "p2-v1"
POLICY_SHA256 = "570a931bc2e98ca5cada78c5fe891e699e43e7c9f513b8df2257c06f1261b7bb"


class ModelLifecyclePolicyError(ValueError):
    pass


def canonical_sha256(value: Mapping[str, Any]) -> str:
    content = dict(value)
    content.pop("policy_sha256", None)
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_model_lifecycle_policy(repository_root: Path = ROOT, deployment_id: str = "dhaka_south", version: str = POLICY_VERSION, expected_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    if deployment_id != "dhaka_south" or version != POLICY_VERSION or expected_sha256 not in (None, POLICY_SHA256):
        raise ModelLifecyclePolicyError("Unknown model lifecycle policy identity.")
    try:
        policy = json.loads((repository_root / "config/deployments/dhaka_south/model_lifecycle_policy.json").read_text(encoding="utf-8"))
        schema = json.loads((repository_root / "config/runtime_model_lifecycle_policy.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(policy)
    except Exception as exc:
        raise ModelLifecyclePolicyError("The model lifecycle policy is unavailable or invalid.") from exc
    digest = canonical_sha256(policy)
    if digest != POLICY_SHA256 or policy.get("policy_sha256") != POLICY_SHA256:
        raise ModelLifecyclePolicyError("The model lifecycle policy hash is invalid.")
    forbidden = ("automaticPromotionAllowed", "automaticRollbackAllowed", "automaticRetentionAllowed", "thresholdBasedActionAllowed", "arbitraryModelSelectionAllowed", "arbitraryRollbackTargetAllowed", "baselineAssignmentAllowed", "profileMutationAllowed", "unknownIdentityFallbackAllowed", "materialWorseningClassificationRequired", "lifecycleRecommendationFromDegradationEvidenceAllowed", "nonRandomForestActivationAllowed", "assignmentHistoryMutationAllowed")
    if any(policy.get(key) is not False for key in forbidden) or policy.get("operatorDecisionRequired") is not True or policy.get("activeQuickForecastPolicyRequired") is not True:
        raise ModelLifecyclePolicyError("Automatic, arbitrary, or non-Random-Forest lifecycle action is prohibited.")
    return policy, digest
