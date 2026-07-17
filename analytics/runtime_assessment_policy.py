"""Versioned, side-effect-free dataset-assessment governance evaluation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parent.parent
POLICY_SCHEMA_PATH = ROOT / "config" / "runtime_assessment_policy.schema.json"
CANDIDATE_SCHEMA_PATH = ROOT / "config" / "candidate_models.schema.json"
CANDIDATE_REGISTRY_PATH = ROOT / "config" / "candidate_models.json"

REASON_MESSAGES = {
    "assessment_policy_inactive": "The governed dataset-assessment policy is not active.",
    "validation_failed": "Authoritative dataset validation did not pass.",
    "deployment_mismatch": "The dataset is not bound to the assessment deployment.",
    "geography_mismatch": "The uploaded geography does not exactly match Dhaka South city scope.",
    "source_scope_mismatch": "The uploaded source or aggregation metadata is outside the governed assessment scope.",
    "canonical_contract_mismatch": "The canonical uploaded-data contract differs from the assessment policy.",
    "feature_contract_mismatch": "The governed 18-feature contract could not be reproduced exactly.",
    "target_mismatch": "The target differs from the governed two-week case target.",
    "horizon_mismatch": "The forecast horizon differs from the governed two-week horizon.",
    "non_contiguous_history": "Assessment requires chronological, duplicate-free, contiguous aligned history.",
    "candidate_registry_mismatch": "The candidate registry differs from the assessment policy binding.",
    "insufficient_labelled_rows": "The dataset has fewer labelled rows than the active assessment policy requires.",
    "insufficient_planned_folds": "The dataset has fewer temporal folds than the active assessment policy requires.",
    "fold_cap_governance_pending": "The dataset provides more than 68 folds, but a larger runtime fold cap and selection rule are not yet governed.",
    "no_eligible_baseline": "No governed naive baseline is eligible for the common fold plan.",
    "no_eligible_learned_model": "No deployable learned candidate is eligible for the common fold plan.",
    "insufficient_candidate_breadth": "At least two candidates, including a naive baseline and a deployable learned model, are required.",
    "recommendation_strength_not_governed": "Recommendation-strength thresholds are not yet governed; any future technical winner is evidence only.",
}


class RuntimeAssessmentPolicyError(ValueError):
    """Raised when policy bytes, schema, or bound repository identities are invalid."""


def canonical_policy_sha256(policy: Mapping[str, Any]) -> str:
    content = dict(policy)
    content.pop("policy_sha256", None)
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def policy_path(deployment_id: str, policy_version: str | None = None) -> Path:
    if not deployment_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in deployment_id):
        raise RuntimeAssessmentPolicyError("Invalid deployment identifier for dataset-assessment policy.")
    parent = (ROOT / "config" / "deployments" / deployment_id).resolve()
    if policy_version in (None, "p2-v1"):
        filename = "assessment_policy.json"
    elif policy_version == "p1.4d-1-v1":
        filename = "assessment_policy_p1.4d-1-v1.json"
    else:
        raise RuntimeAssessmentPolicyError("Unsupported dataset-assessment policy version.")
    path = (parent / filename).resolve()
    if path.parent != parent:
        raise RuntimeAssessmentPolicyError("Dataset-assessment policy path escaped its deployment directory.")
    return path


def load_and_validate_assessment_policy(
    deployment_id: str, policy_version: str | None = None,
    expected_sha256: str | None = None,
) -> tuple[dict[str, Any], str]:
    path = policy_path(deployment_id, policy_version)
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
        registry_bytes = CANDIDATE_REGISTRY_PATH.read_bytes()
        registry = json.loads(registry_bytes.decode("utf-8"))
        registry_schema = json.loads(CANDIDATE_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeAssessmentPolicyError("Dataset-assessment policy dependencies are not valid UTF-8 JSON.") from exc

    errors = [
        error.message
        for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(policy)
    ]
    errors.extend(error.message for error in Draft202012Validator(registry_schema).iter_errors(registry))
    computed = canonical_policy_sha256(policy)
    if policy.get("policy_sha256") != computed:
        errors.append("Dataset-assessment policy hash mismatch.")
    if policy_version is not None and policy.get("policy_version") != policy_version:
        errors.append("Dataset-assessment policy version resolution mismatch.")
    if expected_sha256 is not None and computed != expected_sha256:
        errors.append("Dataset-assessment policy expected hash mismatch.")

    profile_path = ROOT / "config" / "deployments" / deployment_id / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    geography = policy.get("geography_scope", {})
    expected_geography = profile.get("geography", {})
    if policy.get("deployment_id") != profile.get("deployment_id"):
        errors.append("Assessment policy deployment differs from the deployment profile.")
    if (geography.get("level"), geography.get("id"), geography.get("name")) != (
        expected_geography.get("level"), expected_geography.get("id"), expected_geography.get("name")
    ):
        errors.append("Assessment policy geography differs from the deployment profile.")

    registry_sha = hashlib.sha256(registry_bytes).hexdigest()
    if policy.get("candidate_registry", {}).get("sha256") != registry_sha:
        errors.append("Assessment policy candidate-registry hash mismatch.")
    if policy.get("candidate_registry", {}).get("version") != registry.get("candidate_registry_version"):
        errors.append("Assessment policy candidate-registry version mismatch.")
    if policy.get("feature_contract", {}).get("feature_order_sha256") != registry.get("feature_order_sha256"):
        errors.append("Assessment policy feature-order hash differs from the candidate registry.")
    if policy.get("input_contract", {}).get("target") != registry.get("target"):
        errors.append("Assessment policy target differs from the candidate registry.")
    if policy.get("input_contract", {}).get("horizon_weeks") != registry.get("horizon_weeks"):
        errors.append("Assessment policy horizon differs from the candidate registry.")

    policy_candidates = policy.get("candidate_eligibility_policy", {}).get("candidates", [])
    registry_candidates = registry.get("candidates", [])
    if [value.get("model_id") for value in policy_candidates] != [value.get("model_id") for value in registry_candidates]:
        errors.append("Assessment policy candidate order differs from the candidate registry.")
    for governed, registered in zip(policy_candidates, registry_candidates):
        for policy_key, registry_key in (
            ("model_family", "model_family"),
            ("parameters_sha256", "parameters_sha256"),
            ("minimum_training_rows", "minimum_training_rows"),
            ("negative_output_policy", "negative_prediction_policy"),
            ("selection_complexity_rank", "selection_complexity_rank"),
        ):
            if governed.get(policy_key) != registered.get(registry_key):
                errors.append(f"Assessment policy candidate {governed.get('model_id')} {policy_key} mismatch.")
        if governed.get("deterministic_configuration") != registered.get("parameters"):
            errors.append(f"Assessment policy candidate {governed.get('model_id')} parameter configuration mismatch.")
        if registered.get("enabled") is not True:
            errors.append(f"Assessment policy candidate {governed.get('model_id')} is disabled in the registry.")

    if errors:
        raise RuntimeAssessmentPolicyError(" ".join(dict.fromkeys(errors)))
    return policy, computed


def available_fold_count(labelled_rows: int, fold_policy: Mapping[str, Any]) -> int:
    """Count folds without generating descriptors or accessing observations."""
    initial = int(fold_policy["initial_training_rows"])
    embargo = int(fold_policy["embargo_rows"])
    step = int(fold_policy["step_size_weeks"])
    first_validation_index = initial + embargo
    return len(range(first_validation_index, max(0, int(labelled_rows)), step))


def select_planned_validation_indexes(
    labelled_row_count: int,
    initial_training_rows: int,
    embargo_rows: int,
    minimum_fold_count: int,
    maximum_fold_count: int,
) -> tuple[int, ...]:
    """Select the deterministic recent validation window without file access."""
    values = (labelled_row_count, initial_training_rows, embargo_rows, minimum_fold_count, maximum_fold_count)
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        raise RuntimeAssessmentPolicyError("Fold selection parameters must be integers.")
    if initial_training_rows < 1 or embargo_rows < 0 or minimum_fold_count < 1 or maximum_fold_count < minimum_fold_count:
        raise RuntimeAssessmentPolicyError("Fold selection parameters are invalid.")
    first = initial_training_rows + embargo_rows
    available = tuple(range(first, max(0, labelled_row_count)))
    if len(available) < minimum_fold_count:
        raise RuntimeAssessmentPolicyError("Insufficient temporal folds for dataset assessment.")
    return available[-maximum_fold_count:]


def _matches_geography(actual: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(actual, Mapping) and (
        actual.get("geography_level"), actual.get("geography_id"), actual.get("geography_name")
    ) == (expected.get("level"), expected.get("id"), expected.get("name"))


def evaluate_assessment_policy(policy: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate governance only; never generate folds, fit candidates, or choose a winner."""
    blocking_codes: list[str] = []

    def fail(code: str, condition: bool) -> None:
        if condition and code not in blocking_codes:
            blocking_codes.append(code)

    fail("assessment_policy_inactive", policy.get("policy_status") != "active")
    fail("validation_failed", context.get("validation_passed") is not True)
    fail("deployment_mismatch", context.get("deployment_id") != policy.get("deployment_id"))
    geography = policy.get("geography_scope", {})
    fail("geography_mismatch", not _matches_geography(context.get("case_geography"), geography)
         or not _matches_geography(context.get("climate_geography"), geography))
    contract = policy.get("input_contract", {})
    fail("canonical_contract_mismatch", context.get("canonical_contract_version") != contract.get("canonical_contract_version"))
    fail("target_mismatch", context.get("target") != contract.get("target"))
    fail("horizon_mismatch", context.get("horizon_weeks") != contract.get("horizon_weeks"))
    feature_contract = policy.get("feature_contract", {})
    fail("feature_contract_mismatch", context.get("feature_order_sha256") != feature_contract.get("feature_order_sha256")
         or context.get("constructible_feature_count") != feature_contract.get("feature_count"))
    fail("non_contiguous_history", not all(context.get(name) is True for name in (
        "chronological_order_valid", "duplicate_periods_absent", "contiguous_history", "case_climate_aligned"
    )))

    source_scope = policy.get("source_scope", {})
    for domain in ("cases", "climate"):
        actual = context.get("source_metadata", {}).get(domain, {})
        permitted = source_scope.get(domain, {})
        fail("source_scope_mismatch", actual.get("source_type") not in permitted.get("allowed_source_types", [])
             or actual.get("aggregation_method") not in permitted.get("allowed_aggregation_methods", [])
             or actual.get("contains_approximated_values") is not False)

    registry = context.get("candidate_registry", {})
    registry_sha = context.get("candidate_registry_sha256")
    expected_registry = policy.get("candidate_registry", {})
    registry_matches = (
        registry_sha == expected_registry.get("sha256")
        and registry.get("candidate_registry_version") == expected_registry.get("version")
        and registry.get("feature_order_sha256") == feature_contract.get("feature_order_sha256")
        and registry.get("target") == contract.get("target")
        and registry.get("horizon_weeks") == contract.get("horizon_weeks")
    )
    fail("candidate_registry_mismatch", not registry_matches)

    fold_policy = policy.get("fold_policy", {})
    labelled_rows = max(0, int(context.get("labelled_rows", 0)))
    available = available_fold_count(labelled_rows, fold_policy)
    is_phase_two = policy.get("policy_version") == "p2-v1"
    minimum_rows = int(fold_policy.get("minimum_labelled_rows",
        fold_policy.get("recommendation_grade_minimum_labelled_rows", 0)))
    minimum_folds = int(fold_policy.get("minimum_fold_count",
        fold_policy.get("recommendation_grade_minimum_folds", 0)))
    maximum_folds = int(fold_policy.get("maximum_fold_count",
        fold_policy.get("maximum_fold_behavior", {}).get("currently_governed_maximum_folds", 0)))
    if labelled_rows < minimum_rows:
        fail("insufficient_labelled_rows", True)
    if available < minimum_folds:
        fail("insufficient_planned_folds", True)
    maximum = fold_policy.get("maximum_fold_behavior", {}).get("currently_governed_maximum_folds")
    if not is_phase_two and maximum is not None and available > int(maximum):
        fail("fold_cap_governance_pending", True)
    if is_phase_two:
        planned = min(available, maximum_folds) if available >= minimum_folds else 0
    else:
        planned = available if not (maximum is not None and available > int(maximum)) else 0
    fold_cap_applied = bool(is_phase_two and available > maximum_folds)
    selected_indexes = tuple(range(labelled_rows - planned, labelled_rows)) if planned else ()

    registry_by_id = {value.get("model_id"): value for value in registry.get("candidates", [])}
    prerequisite_overrides = context.get("candidate_prerequisites", {})
    candidates: dict[str, Any] = {}
    eligible_ids: list[str] = []
    for governed in policy.get("candidate_eligibility_policy", {}).get("candidates", []):
        model_id = governed["model_id"]
        registered = registry_by_id.get(model_id, {})
        overrides = prerequisite_overrides.get(model_id, {})
        reasons: list[str] = []
        if not registry_matches or registered.get("parameters_sha256") != governed.get("parameters_sha256"):
            reasons.append("candidate_registry_mismatch")
        if labelled_rows < int(governed.get("minimum_training_rows", 0)):
            reasons.append("insufficient_candidate_training_rows")
        if int(context.get("available_history_weeks", 0)) < int(governed.get("seasonal_history_weeks", 0)):
            reasons.append("seasonal_history_unavailable")
        for key, code in (
            ("required_features_available", "required_features_unavailable"),
            ("source_compatible", "candidate_source_incompatible"),
            ("fold_plan_compatible", "candidate_fold_plan_incompatible"),
        ):
            if overrides.get(key, True) is not True:
                reasons.append(code)
        if overrides.get("parameters_sha256", governed.get("parameters_sha256")) != governed.get("parameters_sha256"):
            reasons.append("candidate_parameter_mismatch")
        eligible = not reasons
        if eligible:
            eligible_ids.append(model_id)
        candidates[model_id] = {
            "eligible": eligible,
            "reasonCodes": reasons if reasons else ["candidate_prerequisites_satisfied"],
            "reasons": [REASON_MESSAGES.get(code, code.replace("_", " ").capitalize() + ".") for code in reasons]
                       if reasons else ["Candidate prerequisites are satisfied for the precommitted common fold plan."],
            "candidateClass": governed["candidate_class"],
            "deployabilityClassification": governed["deployability_classification"],
            "parametersSha256": governed["parameters_sha256"],
            "minimumTrainingRows": governed["minimum_training_rows"],
        }

    naive = [model_id for model_id in eligible_ids if candidates[model_id]["candidateClass"] == "naive_baseline"]
    learned = [model_id for model_id in eligible_ids if candidates[model_id]["deployabilityClassification"] == "deployable_learned_model"]
    if not naive:
        fail("no_eligible_baseline", True)
    if not learned:
        fail("no_eligible_learned_model", True)
    if len(eligible_ids) < 2:
        fail("insufficient_candidate_breadth", True)

    all_candidate_ids = [value["model_id"] for value in policy.get("candidate_eligibility_policy", {}).get("candidates", [])]
    candidate_set_status = (
        "insufficient_candidate_breadth" if not naive or not learned or len(eligible_ids) < 2
        else "complete_candidate_set" if eligible_ids == all_candidate_ids
        else "partial_candidate_set"
    )
    history_blockers = {"insufficient_labelled_rows", "insufficient_planned_folds"}
    identity_blockers = set(blocking_codes) - history_blockers - {"fold_cap_governance_pending", "no_eligible_baseline", "no_eligible_learned_model", "insufficient_candidate_breadth"}
    if "assessment_policy_inactive" in blocking_codes:
        status = "assessment_policy_inactive"
    elif identity_blockers or "fold_cap_governance_pending" in blocking_codes or candidate_set_status == "insufficient_candidate_breadth":
        status = "assessment_blocked"
    elif history_blockers & set(blocking_codes):
        status = "insufficient_history"
    elif candidate_set_status == "partial_candidate_set":
        status = "partial_candidate_set"
    else:
        status = "full_assessment_eligible"

    eligible = status in {"full_assessment_eligible", "partial_candidate_set"}
    recommendation_policy = policy.get("recommendation_policy", {})
    recommendation_status = "evidence_only" if eligible else "no_recommendation"
    reason_codes = list(blocking_codes)
    if eligible and recommendation_policy.get("strength_threshold_status") != "governed":
        reason_codes.append("recommendation_strength_not_governed")
    if not reason_codes:
        reason_codes.append("assessment_policy_requirements_satisfied")
    reasons = [REASON_MESSAGES.get(code, "Dataset assessment policy requirements are satisfied.") for code in reason_codes]

    return {
        "eligible": eligible,
        "assessmentStatus": status,
        "assessmentEligibilityStatus": status,
        "labelledRows": labelled_rows,
        "availableFoldCount": available,
        "plannedFoldCount": planned,
        "minimumFoldCount": minimum_folds,
        "maximumFoldCount": maximum_folds,
        "foldCapApplied": fold_cap_applied,
        "selectedValidationStartIndex": selected_indexes[0] if selected_indexes else None,
        "selectedValidationEndIndex": selected_indexes[-1] if selected_indexes else None,
        "foldPlan": {
            "trainingWindow": fold_policy.get("training_window"),
            "initialTrainingRows": fold_policy.get("initial_training_rows"),
            "embargoRows": fold_policy.get("embargo_rows"),
            "validationRowsPerFold": fold_policy.get("validation_rows_per_fold"),
            "stepSizeWeeks": fold_policy.get("step_size_weeks"),
            "horizonWeeks": fold_policy.get("target_horizon_weeks"),
            "samePlanForAllCandidates": fold_policy.get("same_precomputed_plan_for_all_candidates"),
            "firstAvailableValidationIndex": int(fold_policy.get("first_available_validation_index",
                int(fold_policy.get("initial_training_rows", 0)) + int(fold_policy.get("embargo_rows", 0)))),
            "minimumFoldCount": minimum_folds,
            "maximumFoldCount": maximum_folds,
            "foldSelectionRule": fold_policy.get("fold_selection_rule"),
            "maximumFoldCapStatus": "applied" if fold_cap_applied else "not_applied" if is_phase_two else fold_policy.get("maximum_fold_behavior", {}).get("status"),
        },
        "decisionCompatibilityStatus": policy.get("decision_compatibility", {}).get("status", "phase1_decision_policy_available"),
        "candidateSetStatus": candidate_set_status,
        "candidateEligibility": candidates,
        "recommendationEligibility": False,
        "recommendationStatus": recommendation_status,
        "recommendationStrength": "not_available",
        "approvalRequired": bool(policy.get("approval_requirement", {}).get("required_before_adoption")),
        "approvalEnabled": False,
        "reasonCodes": reason_codes,
        "reasons": reasons,
        "policyId": policy.get("policy_id"),
        "policyVersion": policy.get("policy_version"),
        "policySha256": policy.get("policy_sha256"),
        "assessmentPolicyId": policy.get("policy_id"),
        "assessmentPolicyVersion": policy.get("policy_version"),
        "assessmentPolicySha256": policy.get("policy_sha256"),
    }
