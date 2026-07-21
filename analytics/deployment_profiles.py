"""Deployment-profile loading, semantic validation, and run governance."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jsonschema import Draft202012Validator, FormatChecker

from evidence_registry import (
    EvidenceRegistryError, evidence_registry_sha256, load_evidence_registry,
    validate_formula_evidence_links,
)
from formula_registry import (
    DEPLOYMENT_GATES, FormulaRegistryError, effective_maximum_gate, get_formula,
    known_formula_ids, load_formula_registry, registry_sha256,
)
from input_sources import CASE_SOURCES, CLIMATE_SOURCES, OPERATIONAL_SOURCES, get_source_descriptor

ROOT = Path(__file__).resolve().parent.parent
DEPLOYMENTS_DIR = ROOT / "config" / "deployments"
PROFILE_SCHEMA_PATH = ROOT / "config" / "deployment_profile.schema.json"
MODEL_CARD_SCHEMA_PATH = ROOT / "config" / "model_card.schema.json"
CANDIDATE_REGISTRY_PATH = ROOT / "config" / "candidate_models_p1.2a-v1.json"
DEPLOYMENT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class DeploymentProfileError(ValueError):
    """Raised when a deployment profile or model card violates governance."""


def deployment_profile_sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _validate_schema(value: Any, schema_path: Path, label: str) -> None:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    errors = [error.message for error in sorted(validator.iter_errors(value), key=lambda e: list(e.path))]
    if errors:
        raise DeploymentProfileError(f"{label} schema validation failed: {' '.join(errors)}")


def _profile_path(deployment_id: str) -> Path:
    if not DEPLOYMENT_ID_PATTERN.fullmatch(deployment_id):
        raise DeploymentProfileError(f"Invalid deployment ID: {deployment_id!r}.")
    path = (DEPLOYMENTS_DIR / deployment_id / "profile.json").resolve()
    expected_parent = (DEPLOYMENTS_DIR / deployment_id).resolve()
    if path.parent != expected_parent:
        raise DeploymentProfileError("Deployment profile path escapes its deployment directory.")
    return path


def validate_deployment_profile(
    profile: dict[str, Any],
    *,
    profile_path: str | Path | None = None,
    executable: bool = True,
) -> None:
    _validate_schema(profile, PROFILE_SCHEMA_PATH, "Deployment profile")
    errors: list[str] = []
    if profile_path is not None and Path(profile_path).resolve().parent.name != profile["deployment_id"]:
        errors.append("deployment_id does not match its directory name.")
    try:
        ZoneInfo(profile["timezone"])
    except ZoneInfoNotFoundError:
        errors.append(f"Unknown timezone: {profile['timezone']}.")
    try:
        effective = date.fromisoformat(profile["effective_date"])
        review = date.fromisoformat(profile["review_date"])
        if effective > review:
            errors.append("effective_date must not be after review_date.")
    except ValueError:
        errors.append("Profile dates must be valid ISO dates.")
    if executable and profile["status"] in {"retired", "superseded", "suspended"}:
        errors.append(f"Profile status {profile['status']} cannot execute.")

    formulas = load_formula_registry()
    evidence = load_evidence_registry()
    try:
        validate_formula_evidence_links(evidence, formulas)
    except EvidenceRegistryError as exc:
        errors.append(str(exc))
    if profile["formula_registry_version"] != formulas["registry_version"]:
        errors.append("Formula-registry version mismatch.")
    if profile["formula_registry_sha256"] != registry_sha256():
        errors.append("Formula-registry hash mismatch.")
    comparison = profile["candidate_comparison"]
    if comparison["candidate_registry_sha256"] != hashlib.sha256(CANDIDATE_REGISTRY_PATH.read_bytes()).hexdigest():
        errors.append("Candidate-registry hash mismatch.")
    uncertainty = profile["forecast_uncertainty"]
    if uncertainty["active_model_id"] != profile["model"]["model_id"]:
        errors.append("Forecast-uncertainty active model differs from the deployment profile.")
    if uncertainty["active_model_parameters_sha256"] != profile["model"]["model_parameters_sha256"]:
        errors.append("Forecast-uncertainty parameter hash differs from the active model.")
    try:
        candidate_registry = json.loads(CANDIDATE_REGISTRY_PATH.read_text(encoding="utf-8"))
        if comparison["candidate_registry_version"] != candidate_registry["candidate_registry_version"]:
            errors.append("Candidate-registry version mismatch.")
        enabled = [candidate["model_id"] for candidate in candidate_registry["candidates"] if candidate["enabled"]]
        if comparison["enabled_candidate_ids"] != enabled:
            errors.append("Enabled candidate IDs differ from the candidate registry.")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        errors.append(f"Candidate registry is unreadable: {exc}.")
    if profile["evidence_registry_schema_version"] != evidence["evidence_registry_schema_version"]:
        errors.append("Evidence-registry schema version mismatch.")
    if profile["evidence_registry_sha256"] != evidence_registry_sha256():
        errors.append("Evidence-registry hash mismatch.")
    unknown_formulas = sorted(set(profile["formula_ids"]) - known_formula_ids(formulas))
    if unknown_formulas:
        errors.append(f"Unknown formula IDs: {unknown_formulas}.")
    known_evidence = {record["evidence_id"] for record in evidence["evidence"]}
    unknown_evidence = sorted(set(profile["evidence_ids"]) - known_evidence)
    if unknown_evidence:
        errors.append(f"Unknown evidence IDs: {unknown_evidence}.")

    source_sets = {"cases": CASE_SOURCES, "climate": CLIMATE_SOURCES, "operational": OPERATIONAL_SOURCES}
    for domain, allowed in source_sets.items():
        source_id = profile["data_sources"][domain]["source_id"]
        if source_id not in allowed:
            errors.append(f"Unknown {domain} source ID: {source_id}.")
            continue
        descriptor = get_source_descriptor(source_id)
        if descriptor and descriptor.geography_id != profile["geography"]["id"]:
            errors.append(f"{domain} source geography conflicts with profile geography.")
    sources = [profile["data_sources"][domain]["source_id"] for domain in source_sets]
    benchmark_count = sources.count("synthetic_benchmark")
    if benchmark_count not in (0, 3):
        errors.append("Synthetic benchmark source selection must include all three domains.")
    synthetic_profile = profile["data_mode"] == "synthetic_capability_demonstration"
    if synthetic_profile and profile["observed_data_mode"] != "synthetic":
        errors.append("Synthetic capability profile must have observed_data_mode synthetic.")
    if synthetic_profile and any(source != "synthetic_benchmark" for source in sources):
        errors.append("Synthetic benchmark profile cannot select real or non-benchmark sources.")
    if profile["data_mode"] in {"locally_calibrated_deployment", "institution_approved_deployment"} and benchmark_count:
        errors.append("Local or institutional profiles cannot use benchmark sources.")

    if not unknown_formulas:
        maximum = effective_maximum_gate(tuple(profile["formula_ids"]))
        if DEPLOYMENT_GATES.index(profile["deployment_gate"]) > DEPLOYMENT_GATES.index(maximum):
            errors.append(f"Profile gate exceeds formula maximum gate {maximum}.")
        if profile["deployment_gate"] != "benchmark_only":
            for formula_id in profile["formula_ids"]:
                formula = get_formula(formula_id, formulas)
                if formula["category"] == "synthetic_benchmark_only" or formula["deployment_gate"] == "benchmark_only":
                    errors.append(f"Benchmark-only formula {formula_id} cannot be used above benchmark_only.")
                if formula["institutional_approval_required"] and not profile["approval_record_ids"]:
                    errors.append(f"Institution-required formula {formula_id} lacks approval records.")

    gate = profile["deployment_gate"]
    if gate == "locally_backtested" and not profile["evidence_ids"]:
        errors.append("locally_backtested requires validation evidence.")
    if gate in {"institution_approved", "shadow_validated", "operational_advisory"} and not profile["approval_record_ids"]:
        errors.append(f"{gate} requires approval records.")
    if gate in {"shadow_validated", "operational_advisory"}:
        shadow_ids = {record["evidence_id"] for record in evidence["evidence"] if record["source_type"] == "shadow_validation_result" and record["verification_status"] == "verified"}
        if not shadow_ids.intersection(profile["evidence_ids"]):
            errors.append(f"{gate} requires verified shadow-validation evidence.")
    if synthetic_profile and gate != "benchmark_only":
        errors.append("Synthetic capability demonstration must remain benchmark_only.")
    if profile["data_mode"] == "institution_approved_deployment" and not profile["approval_record_ids"]:
        errors.append("Institution-approved data mode requires approval records.")

    required_claims = ("not locally calibrated", "not a clinical case definition", "official surveillance definition")
    combined = " ".join([profile["maturity_statements"]["prohibited_claim"], profile["case_definition"]]).lower()
    for claim in required_claims:
        if claim not in combined:
            errors.append(f"Profile is missing required claim boundary: {claim}.")
    if errors:
        raise DeploymentProfileError(" ".join(dict.fromkeys(errors)))


def load_deployment_profile(deployment_id: str) -> dict[str, Any]:
    path = _profile_path(deployment_id)
    if not path.is_file():
        raise DeploymentProfileError(f"Unknown deployment profile: {deployment_id}.")
    try:
        profile = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentProfileError(f"Deployment profile is unreadable: {exc}") from exc
    validate_deployment_profile(profile, profile_path=path)
    return profile


def resolve_profile_run_configuration(profile: Mapping[str, Any], cli_values: Mapping[str, Any]) -> dict[str, Any]:
    resolved: dict[str, Any] = {}
    profile_values = {
        "case_source": profile["data_sources"]["cases"]["source_id"],
        "climate_source": profile["data_sources"]["climate"]["source_id"],
        "operational_source": profile["data_sources"]["operational"]["source_id"],
        "deployment_gate": profile["deployment_gate"],
    }
    for key, profile_value in profile_values.items():
        cli_value = cli_values.get(key)
        if cli_value is not None and cli_value != profile_value:
            raise DeploymentProfileError(f"CLI {key}={cli_value!r} conflicts with profile value {profile_value!r}.")
        resolved[key] = profile_value if cli_value is None else cli_value
    return resolved


def build_profile_provenance(profile: Mapping[str, Any], profile_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(profile_path) if profile_path else _profile_path(str(profile["deployment_id"]))
    model = profile["model"]
    return {
        "deployment_profile_id": profile["deployment_id"],
        "deployment_profile_schema_version": profile["profile_schema_version"],
        "deployment_profile_sha256": deployment_profile_sha256(path),
        "deployment_profile_status": profile["status"],
        "deployment_profile_data_mode": profile["data_mode"],
        "observed_data_mode": profile["observed_data_mode"],
        "evidence_registry_schema_version": profile["evidence_registry_schema_version"],
        "evidence_registry_version": load_evidence_registry()["evidence_registry_version"],
        "evidence_registry_sha256": profile["evidence_registry_sha256"],
        "formula_registry_version": profile["formula_registry_version"],
        "formula_registry_sha256": profile["formula_registry_sha256"],
        "model_card_id": model["model_card_id"],
        "model_card_version": model["model_card_version"],
        "candidate_registry_sha256": profile["candidate_comparison"]["candidate_registry_sha256"],
        "active_model_id": model["model_id"],
        "active_model_parameters_sha256": model["model_parameters_sha256"],
        "adoption_status": profile["candidate_comparison"]["selected_model_adoption_status"],
        "adoption_policy_version": profile["candidate_comparison"]["adoption_policy_version"],
        "uncertainty_method_id": profile["forecast_uncertainty"]["method_id"],
        "uncertainty_method_version": profile["forecast_uncertainty"]["method_version"],
        "uncertainty_status": profile["forecast_uncertainty"]["calibration_status"],
    }


def validate_model_card_against_profile(model_card: dict[str, Any], profile: Mapping[str, Any]) -> None:
    _validate_schema(model_card, MODEL_CARD_SCHEMA_PATH, "Model card")
    expected = build_profile_provenance(profile)
    errors: list[str] = []
    comparisons = {
        "deployment_id": profile["deployment_id"], "model_card_id": profile["model"]["model_card_id"],
        "model_card_version": profile["model"]["model_card_version"], "model_id": profile["model"]["model_id"],
        "model_version": profile["model"]["model_version"], "formula_registry_sha256": profile["formula_registry_sha256"],
        "deployment_profile_sha256": expected["deployment_profile_sha256"],
        "evidence_registry_sha256": profile["evidence_registry_sha256"], "deployment_gate": profile["deployment_gate"],
        "data_mode": profile["data_mode"], "observed_data_mode": profile["observed_data_mode"],
    }
    for key, value in comparisons.items():
        if model_card.get(key) != value:
            errors.append(f"Model card {key} does not match deployment profile.")
    if model_card.get("evidence_ids") != profile["evidence_ids"]:
        errors.append("Model card evidence IDs do not match deployment profile.")
    if model_card.get("approval_record_ids") != profile["approval_record_ids"]:
        errors.append("Model card approval records do not match deployment profile.")
    if model_card.get("deprecated_compatibility_fields") != profile["deprecated_compatibility_fields"]:
        errors.append("Model card technical-debt status does not match deployment profile.")
    debt = profile["deprecated_compatibility_fields"]
    if debt.get("status") == "resolved" and (
        debt.get("legacy_fields_emitted") is not False
        or debt.get("compatibility_alias_emission") != "prohibited"
    ):
        errors.append("Resolved canonical-only profile permits legacy compatibility aliases.")
    provenance = model_card.get("provenance", {})
    for key in ("deployment_profile_sha256", "formula_registry_sha256", "evidence_registry_sha256", "model_card_id", "model_card_version"):
        if provenance.get(key) != expected.get(key):
            errors.append(f"Model card provenance {key} is inconsistent.")
    if model_card["deployment_gate"] != "benchmark_only" and model_card["approval_status"] != "approved":
        errors.append("Model card gate and approval status are inconsistent.")
    mandatory_explainability_statement = (
        "Feature importance is a model diagnostic and does not establish causality, "
        "biological mechanism, clinical importance, or stability across seasons."
    )
    if model_card.get("explainability_status") != "generated":
        errors.append("Profiled model card must record generated explainability.")
    if model_card.get("explainability_artifact_path") != "data/selected_model_explainability.json":
        errors.append("Model card explainability artifact path is not canonical.")
    if mandatory_explainability_statement not in model_card.get("explainability_limitations", []):
        errors.append("Model card lacks the mandatory non-causal explainability statement.")
    if model_card.get("explainability_evaluation", {}).get("estimator_role") != "selected_model_chronological_holdout_validation_instance":
        errors.append("Model card explainability estimator role is invalid.")
    if model_card.get("current_forecast_model") != profile["candidate_comparison"]["current_active_forecast_model"]:
        errors.append("Model card active model differs from the deployment profile.")
    if model_card.get("adopted_model_parameters_sha256") != profile["model"]["model_parameters_sha256"]:
        errors.append("Model card active parameter hash differs from the deployment profile.")
    if model_card.get("selected_model_adoption_status") != profile["candidate_comparison"]["selected_model_adoption_status"]:
        errors.append("Model card adoption status differs from the deployment profile.")
    if errors:
        raise DeploymentProfileError(" ".join(errors))
