"""Strict loading for current governed descriptive degradation evidence."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from runtime_context import ROOT

POLICY_ID = "RUNTIME.MODEL_DEGRADATION.EVIDENCE"
POLICY_VERSION = "p2-v2"
POLICY_SHA = "69db63b59f6e0dbbd5d45e98868ce0cafae1a9407d23595c89ec52491b713c98"
MONITORING_SHA = "5c3e1f7f14ab6a0a2fbc28639411a0269224b6f71746a315b9c6e159a6eacca6"
HISTORICAL_POLICY_SHA = "bb13b8ec1991c0587656bf4f202334dddb115135d3ac055fee21b5f5e44f3321"
HISTORICAL_MONITORING_SHA = "c73461e211e334733309232806fa2d41c2e5fdce7aa5e096d065e13e7525eaab"


class ModelDegradationPolicyError(ValueError):
    pass


def canonical_policy_sha256(value: Mapping[str, Any]) -> str:
    content = dict(value); content.pop("policy_sha256", None)
    return hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def load_and_validate_model_degradation_policy(deployment_id: str = "dhaka_south", schema_version: str = "2.0", policy_version: str = POLICY_VERSION, policy_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    current=(deployment_id,schema_version,policy_version)==("dhaka_south","2.0",POLICY_VERSION)
    historical=(deployment_id,schema_version,policy_version)==("dhaka_south","1.0","p2-v1")
    if not current and not historical:
        raise ModelDegradationPolicyError("Unknown model-degradation policy identity.")
    path = ROOT / "config/deployments/dhaka_south" / ("model_degradation_evidence_policy.json" if current else "model_degradation_evidence_policy_p2-v1.json")
    schema_path = ROOT / "config/runtime_model_degradation_evidence_policy.schema.json"
    try:
        policy = json.loads(path.read_text(encoding="utf-8")); schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ModelDegradationPolicyError("Model-degradation policy cannot be read.") from exc
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy), key=lambda error:list(error.path))
    digest = canonical_policy_sha256(policy)
    expected_policy_sha=POLICY_SHA if current else HISTORICAL_POLICY_SHA
    expected_monitoring = {"policy_id":"RUNTIME.FORECAST_OUTCOME.MONITORING","policy_version":"p2-v2","policy_sha256":MONITORING_SHA,"schema_version":"2.1"} if current else {"policy_id":"RUNTIME.FORECAST_OUTCOME.MONITORING","policy_version":"p2-v1","policy_sha256":HISTORICAL_MONITORING_SHA}
    if errors or digest != expected_policy_sha or policy.get("policy_sha256") != expected_policy_sha or policy_sha256 not in (None, expected_policy_sha):
        raise ModelDegradationPolicyError("Model-degradation policy schema or hash is invalid.")
    expected_identity=("2.0",POLICY_ID,POLICY_VERSION,"active",deployment_id) if current else ("1.0",POLICY_ID,"p2-v1","active",deployment_id)
    if (policy.get("schema_version"), policy.get("policy_id"), policy.get("policy_version"), policy.get("policy_status"), policy.get("deployment_id")) != expected_identity:
        raise ModelDegradationPolicyError("Model-degradation policy identity is invalid.")
    if policy.get("accepted_monitoring_policy") != expected_monitoring or policy.get("degradationThresholdStatus") != "not_governed" or policy.get("degradationThresholds") is not None:
        raise ModelDegradationPolicyError("Model-degradation governance boundary is invalid.")
    window = policy.get("monitoring_window", {})
    if window.get("windowOutcomeCount") is not None or window.get("windowSampleGovernanceStatus") != "not_governed" or policy.get("materialWorseningClassificationAllowed") is not False or policy.get("lifecycleRecommendationAllowed") is not False or policy.get("statisticalSufficiencyStatus") != "not_governed" or (current and policy.get("lifecycleActionProduced") is not False):
        raise ModelDegradationPolicyError("Classification, numerical windows, and lifecycle actions are not governed.")
    if current and policy.get("accepted_source_families") != ["quick_forecast_p1","quick_forecast_p2","approved_forecast_p1","approved_forecast_p2"]:
        raise ModelDegradationPolicyError("Current monitoring source-family contract is invalid.")
    return policy, digest
