"""Pure P1.4C-1 Quick Forecast compatibility-policy validation and evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent.parent
POLICY_SCHEMA_PATH = ROOT / "config" / "runtime_quick_forecast_policy.schema.json"
CANDIDATE_REGISTRY_PATH = ROOT / "config" / "candidate_models.json"
EXPECTED_CASE_COLUMNS = [
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "city", "cases", "deaths", "deaths_data_status",
    "source_type", "is_approximated", "approximation_method",
]
EXPECTED_CLIMATE_COLUMNS = [
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "latitude", "longitude", "rainfall_mm", "avg_temp_c",
    "humidity_pct", "coverage_days", "source_type", "aggregation_method",
    "is_approximated",
]

REASON_MESSAGES = {
    "validation_failed": "Authoritative dataset validation did not pass.",
    "deployment_mismatch": "The dataset is not bound to the selected deployment.",
    "geography_mismatch": "The uploaded geography does not exactly match Dhaka South city scope.",
    "canonical_contract_mismatch": "The canonical uploaded-data contract is not approved for Quick Forecast.",
    "feature_contract_mismatch": "The governed 18-feature contract could not be reproduced exactly.",
    "target_mismatch": "The forecast target differs from the approved two-week case target.",
    "horizon_mismatch": "The forecast horizon differs from the approved two-week horizon.",
    "source_type_not_approved": "One or more uploaded source types are outside the approved synthetic benchmark scope.",
    "aggregation_not_approved": "One or more source aggregation methods are outside the approved scope.",
    "source_metadata_not_approved": "Approximated source values are not approved for this Quick Forecast scope.",
    "insufficient_quick_history": "Quick Forecast requires at least 111 contiguous overlap weeks and 104 labelled rows.",
    "non_contiguous_history": "Quick Forecast requires chronological, duplicate-free, contiguous aligned history.",
    "invalid_inference_row": "A complete target-independent inference row could not be constructed.",
    "approved_model_mismatch": "The deployment active model differs from the approved Quick Forecast model.",
    "parameter_hash_mismatch": "The active model parameter identity differs from the approved configuration.",
    "candidate_registry_mismatch": "The candidate registry differs from the policy-bound registry.",
    "runtime_upload_not_permitted": "Runtime uploads are not permitted by the current Quick Forecast policy.",
    "policy_inactive": "The Quick Forecast compatibility policy is not active.",
    "deployment_gate_mismatch": "The deployment gate is outside the policy's permitted scope.",
}


class RuntimePolicyError(ValueError):
    """Raised when governed policy bytes or bound repository identities are invalid."""


def canonical_policy_sha256(policy: Mapping[str, Any]) -> str:
    """Hash canonical policy content while excluding its non-self-referential digest field."""
    content = dict(policy)
    content.pop("policy_sha256", None)
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def policy_path(deployment_id: str) -> Path:
    if not deployment_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in deployment_id):
        raise RuntimePolicyError("Invalid deployment identifier for Quick Forecast policy.")
    path = (ROOT / "config" / "deployments" / deployment_id / "quick_forecast_policy.json").resolve()
    expected_parent = (ROOT / "config" / "deployments" / deployment_id).resolve()
    if path.parent != expected_parent:
        raise RuntimePolicyError("Quick Forecast policy path escaped its deployment directory.")
    return path


def load_and_validate_quick_forecast_policy(deployment_id: str) -> tuple[dict[str, Any], str]:
    path = policy_path(deployment_id)
    raw = path.read_bytes()
    try:
        policy = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimePolicyError("Quick Forecast policy is not valid UTF-8 JSON.") from exc
    schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        error.message
        for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy)
    )
    computed = canonical_policy_sha256(policy)
    if policy.get("policy_sha256") != computed:
        errors.append("Quick Forecast policy hash mismatch.")
    profile_path = ROOT / "config" / "deployments" / deployment_id / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    registry_bytes = CANDIDATE_REGISTRY_PATH.read_bytes()
    registry = json.loads(registry_bytes.decode("utf-8"))
    candidate = next((value for value in registry["candidates"] if value["model_id"] == "random_forest"), None)
    if policy.get("deployment_id") != profile.get("deployment_id"):
        errors.append("Policy deployment differs from the deployment profile.")
    expected_geography = profile.get("geography", {})
    geography = policy.get("geography_scope", {})
    if (geography.get("level"), geography.get("id"), geography.get("name")) != (
        expected_geography.get("level"), expected_geography.get("id"), expected_geography.get("name")
    ):
        errors.append("Policy geography differs from the deployment profile.")
    if profile.get("deployment_gate") not in policy.get("deployment_gate_compatibility", []):
        errors.append("Policy does not permit the deployment profile gate.")
    approved = policy.get("approved_model", {})
    if approved.get("model_id") != profile.get("model", {}).get("model_id"):
        errors.append("Policy model differs from the deployment active model.")
    if approved.get("model_family") != profile.get("model", {}).get("model_family"):
        errors.append("Policy model family differs from the deployment profile.")
    if approved.get("parameters_sha256") != profile.get("model", {}).get("model_parameters_sha256"):
        errors.append("Policy parameter hash differs from the deployment profile.")
    if candidate is None or approved.get("parameters_sha256") != candidate.get("parameters_sha256"):
        errors.append("Policy parameter hash differs from the candidate registry.")
    registry_sha = hashlib.sha256(registry_bytes).hexdigest()
    if policy.get("candidate_registry_sha256") != registry_sha:
        errors.append("Policy candidate-registry hash mismatch.")
    feature_contract = policy.get("feature_contract", {})
    if feature_contract.get("feature_order_sha256") != registry.get("feature_order_sha256"):
        errors.append("Policy feature-order hash differs from the candidate registry.")
    input_contract = policy.get("input_contract", {})
    if input_contract.get("target") != registry.get("target") or input_contract.get("forecast_horizon_weeks") != registry.get("horizon_weeks"):
        errors.append("Policy target or horizon differs from the candidate registry.")
    if input_contract.get("required_case_columns") != EXPECTED_CASE_COLUMNS:
        errors.append("Policy case-column contract differs from runtime canonical validation.")
    if input_contract.get("required_climate_columns") != EXPECTED_CLIMATE_COLUMNS:
        errors.append("Policy climate-column contract differs from runtime canonical validation.")
    if errors:
        raise RuntimePolicyError(" ".join(dict.fromkeys(errors)))
    return policy, computed


def _matches_geography(actual: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(actual, Mapping) and (
        actual.get("geography_level"), actual.get("geography_id"), actual.get("geography_name")
    ) == (expected.get("level"), expected.get("id"), expected.get("name"))


def evaluate_quick_forecast_policy(policy: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deterministic compatibility decision without reading data or executing analytics."""
    reason_codes: list[str] = []

    def fail(code: str, condition: bool) -> None:
        if condition and code not in reason_codes:
            reason_codes.append(code)

    fail("policy_inactive", policy.get("policy_status") != "active")
    fail("runtime_upload_not_permitted", policy.get("runtime_upload_permission") is not True)
    fail("validation_failed", context.get("validation_passed") is not True)
    fail("deployment_mismatch", context.get("deployment_id") != policy.get("deployment_id"))
    fail("deployment_gate_mismatch", context.get("deployment_gate") not in policy.get("deployment_gate_compatibility", []))
    expected_geography = policy.get("geography_scope", {})
    fail("geography_mismatch", not _matches_geography(context.get("case_geography"), expected_geography)
         or not _matches_geography(context.get("climate_geography"), expected_geography))
    contract = policy.get("input_contract", {})
    fail("canonical_contract_mismatch", context.get("canonical_contract_version") != contract.get("canonical_contract_version"))
    fail("target_mismatch", context.get("target") != contract.get("target"))
    fail("horizon_mismatch", context.get("horizon_weeks") != contract.get("forecast_horizon_weeks"))
    features = policy.get("feature_contract", {})
    fail("feature_contract_mismatch", context.get("feature_order_sha256") != features.get("feature_order_sha256")
         or context.get("constructible_feature_count") != features.get("feature_count"))
    approved = policy.get("approved_model", {})
    fail("approved_model_mismatch", context.get("approved_model_id") != approved.get("model_id")
         or context.get("approved_model_family") != approved.get("model_family"))
    fail("parameter_hash_mismatch", context.get("approved_model_parameters_sha256") != approved.get("parameters_sha256"))
    fail("candidate_registry_mismatch", context.get("candidate_registry_sha256") != policy.get("candidate_registry_sha256"))

    source_scope = policy.get("source_scope", {})
    for domain in ("cases", "climate"):
        actual = context.get("source_metadata", {}).get(domain, {})
        permitted = source_scope.get(domain, {})
        fail("source_type_not_approved", actual.get("source_type") not in permitted.get("allowed_source_types", []))
        fail("aggregation_not_approved", actual.get("aggregation_method") not in permitted.get("allowed_aggregation_methods", []))
        fail("source_metadata_not_approved", actual.get("contains_approximated_values") is not False)

    minimum = policy.get("minimum_history", {})
    fail("insufficient_quick_history", context.get("overlap_weeks", 0) < minimum.get("minimum_overlap_weeks", 0)
         or context.get("labelled_rows", 0) < minimum.get("minimum_labelled_rows", 0))
    fail("non_contiguous_history", not all(context.get(name) is True for name in (
        "chronological_order_valid", "duplicate_periods_absent", "contiguous_history", "case_climate_aligned"
    )))
    fail("invalid_inference_row", context.get("valid_inference_row") is not True)

    eligible = not reason_codes
    uncertainty = policy.get("uncertainty_policy", {})
    preparedness = policy.get("preparedness_policy", {})
    reasons = ([
        "The uploaded dataset matches the current governed Dhaka South synthetic benchmark deployment contract.",
        "Quick Forecast may use the approved Random Forest configuration for a point forecast; this is not a dataset-specific best-model finding.",
    ] if eligible else [REASON_MESSAGES[code] for code in reason_codes])
    return {
        "eligible": eligible,
        "approvedModelId": approved.get("model_id"),
        "uncertaintyStatus": uncertainty.get("eligible_status") if eligible else uncertainty.get("ineligible_status"),
        "preparednessStatus": preparedness.get("status") if eligible else "unavailable_for_uploaded_dataset",
        "reasonCodes": reason_codes if reason_codes else ["compatible_with_governed_scope"],
        "reasons": reasons,
        "policyId": policy.get("policy_id"),
        "policyVersion": policy.get("policy_version"),
        "policySha256": policy.get("policy_sha256"),
    }
