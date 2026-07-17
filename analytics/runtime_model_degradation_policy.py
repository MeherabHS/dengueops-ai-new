"""Strict loading for the first governed model-degradation evidence policy."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from runtime_context import ROOT

POLICY_ID = "RUNTIME.MODEL_DEGRADATION.EVIDENCE"
POLICY_VERSION = "p2-v1"
POLICY_SHA = "bb13b8ec1991c0587656bf4f202334dddb115135d3ac055fee21b5f5e44f3321"
MONITORING_SHA = "c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab"


class ModelDegradationPolicyError(ValueError):
    pass


def canonical_policy_sha256(value: Mapping[str, Any]) -> str:
    content = dict(value); content.pop("policy_sha256", None)
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_and_validate_model_degradation_policy(deployment_id: str = "dhaka_south", schema_version: str = "1.0", policy_version: str = POLICY_VERSION, policy_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    if (deployment_id, schema_version, policy_version) != ("dhaka_south", "1.0", POLICY_VERSION):
        raise ModelDegradationPolicyError("Unknown model-degradation policy identity.")
    path = ROOT / "config/deployments/dhaka_south/model_degradation_evidence_policy.json"
    schema_path = ROOT / "config/runtime_model_degradation_evidence_policy.schema.json"
    try:
        policy = json.loads(path.read_text(encoding="utf-8")); schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ModelDegradationPolicyError("Model-degradation policy cannot be read.") from exc
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy), key=lambda error:list(error.path))
    digest = canonical_policy_sha256(policy)
    expected_monitoring = {"policy_id":"RUNTIME.FORECAST_OUTCOME.MONITORING","policy_version":"p2-v1","policy_sha256":MONITORING_SHA}
    if errors or digest != POLICY_SHA or policy.get("policy_sha256") != POLICY_SHA or policy_sha256 not in (None, POLICY_SHA):
        raise ModelDegradationPolicyError("Model-degradation policy schema or hash is invalid.")
    if (policy.get("schema_version"), policy.get("policy_id"), policy.get("policy_version"), policy.get("policy_status"), policy.get("deployment_id")) != ("1.0", POLICY_ID, POLICY_VERSION, "active", deployment_id):
        raise ModelDegradationPolicyError("Model-degradation policy identity is invalid.")
    if policy.get("accepted_monitoring_policy") != expected_monitoring or policy.get("degradationThresholdStatus") != "not_governed" or policy.get("degradationThresholds") is not None:
        raise ModelDegradationPolicyError("Model-degradation governance boundary is invalid.")
    window = policy.get("monitoring_window", {})
    if window.get("windowOutcomeCount") is not None or window.get("windowSampleGovernanceStatus") != "not_governed" or policy.get("materialWorseningClassificationAllowed") is not False or policy.get("lifecycleRecommendationAllowed") is not False:
        raise ModelDegradationPolicyError("Classification, numerical windows, and lifecycle actions are not governed.")
    return policy, digest
