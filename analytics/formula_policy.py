"""Explicit ID+SHA formula activation authority."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from formula_inputs import INVENTORY_GAP_SLOT, SUPPORTED_FORMULA_SLOTS
from formula_registry import (
    FormulaRegistryError,
    get_governed_formula,
    load_governed_formula_registry,
)

ROOT = Path(__file__).resolve().parent.parent
POLICY_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "formula_activation_policy.json"
POLICY_SCHEMA_PATH = ROOT / "config" / "formula_activation_policy.schema.json"
QUALIFICATION_POLICY_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "qualification" / "formula_activation_policy.json"
QUALIFICATION_POLICY_SCHEMA_PATH = ROOT / "config" / "qualification_formula_activation_policy.schema.json"


class FormulaPolicyError(ValueError):
    """Raised when activation authority is invalid or absent."""


def canonical_policy_sha256(policy: dict[str, Any]) -> str:
    content = {key: value for key, value in policy.items() if key != "policySha256"}
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def policy_raw_sha256(path: str | Path = POLICY_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_formula_activation_policy(policy: Any) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise FormulaPolicyError("Formula activation policy must be an object.")
    schema = json.loads(POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(policy), key=lambda error: list(error.path))
    if errors:
        raise FormulaPolicyError(f"Formula activation policy failed schema validation: {errors[0].message}")
    if policy["policySha256"] != canonical_policy_sha256(policy):
        raise FormulaPolicyError("Formula activation policy hash mismatch.")
    bindings = policy["formulaBindings"]
    if any(slot not in SUPPORTED_FORMULA_SLOTS for slot in bindings):
        raise FormulaPolicyError("Formula activation policy contains an unsupported slot.")
    configured = INVENTORY_GAP_SLOT in bindings
    if configured != (policy["inventoryGapActivationStatus"] == "configured"):
        raise FormulaPolicyError("Formula activation status and binding are inconsistent.")
    if not configured and policy["authorityGate"]["status"] != "not_approved":
        raise FormulaPolicyError("Unconfigured inventory.gap cannot carry approved authority.")
    return dict(policy)


def load_formula_activation_policy(path: str | Path | None = None) -> dict[str, Any]:
    path = path or os.environ.get("DENGUEOPS_OPERATIONAL_FORMULA_POLICY_PATH", str(POLICY_PATH))
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormulaPolicyError("Formula activation policy is unreadable.") from exc
    return validate_formula_activation_policy(policy)


def validate_qualification_formula_policy(
    policy: Any,
    *,
    scenario_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise FormulaPolicyError("Qualification formula policy must be an object.")
    schema = json.loads(QUALIFICATION_POLICY_SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(policy), key=lambda error: list(error.path))
    if errors:
        raise FormulaPolicyError(f"Qualification formula policy failed schema validation: {errors[0].message}")
    if policy["policySha256"] != canonical_policy_sha256(policy):
        raise FormulaPolicyError("Qualification formula policy hash mismatch.")
    from synthetic_hospital_inventory import load_scenario_policy
    scenario = scenario_policy or load_scenario_policy()
    if (policy["scenarioPolicyId"], policy["scenarioPolicySha256"]) != (
        scenario["policyId"], scenario["policySha256"]
    ):
        raise FormulaPolicyError("Qualification scenario-policy binding mismatch.")
    return dict(policy)


def load_qualification_formula_policy(path: str | Path = QUALIFICATION_POLICY_PATH) -> dict[str, Any]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FormulaPolicyError("Qualification formula policy is unreadable.") from exc
    return validate_qualification_formula_policy(policy)


def resolve_qualification_formula(
    slot: str,
    *,
    requested_evidence_scope: str,
    policy: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if requested_evidence_scope != "synthetic_qualification":
        raise FormulaPolicyError("formula_scope_mismatch")
    authority = validate_qualification_formula_policy(policy) if policy is not None else load_qualification_formula_policy()
    if authority["authorityScope"] != requested_evidence_scope or authority["operationalUseAllowed"] is not False:
        raise FormulaPolicyError("formula_scope_mismatch")
    from formula_registry import validate_governed_formula_registry
    catalog = validate_governed_formula_registry(registry) if registry is not None else load_governed_formula_registry()
    binding = authority["formulaBindings"].get(slot)
    if binding is None:
        raise FormulaPolicyError("formula_not_configured")
    try:
        formula = get_governed_formula(binding["activeFormulaId"], catalog)
    except FormulaRegistryError as exc:
        raise FormulaPolicyError("Active qualification formula is not registered.") from exc
    if formula["formulaSlot"] != slot or formula["formulaSha256"] != binding["activeFormulaSha256"]:
        raise FormulaPolicyError("Qualification formula ID/SHA binding mismatch.")
    if formula["status"] != "approved":
        raise FormulaPolicyError("Qualification formula is not approved.")
    return formula


def resolve_active_formula(
    slot: str,
    *,
    policy: dict[str, Any] | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    authority = policy or load_formula_activation_policy()
    registry_path = os.environ.get("DENGUEOPS_OPERATIONAL_FORMULA_REGISTRY_PATH")
    catalog = registry or load_governed_formula_registry(registry_path) if registry_path else registry or load_governed_formula_registry()
    if slot not in SUPPORTED_FORMULA_SLOTS:
        raise FormulaPolicyError("Unsupported formula slot.")
    binding = authority["formulaBindings"].get(slot)
    if binding is None:
        raise FormulaPolicyError("formula_not_configured")
    if authority["authorityGate"]["status"] != "approved" or any(
        value is None for key, value in authority["authorityGate"].items() if key != "status"
    ):
        raise FormulaPolicyError("formula_authority_gate_not_approved")
    try:
        formula = get_governed_formula(binding["activeFormulaId"], catalog)
    except FormulaRegistryError as exc:
        raise FormulaPolicyError("Active formula is not registered.") from exc
    if formula["formulaSlot"] != slot or formula["formulaSha256"] != binding["activeFormulaSha256"]:
        raise FormulaPolicyError("Active formula ID/SHA binding mismatch.")
    if formula["status"] != "approved":
        raise FormulaPolicyError("Active formula is not approved.")
    gate = authority["authorityGate"]
    if formula["outputUnit"] != gate["resourceUnit"] or formula["roundingPolicy"] != gate["roundingRule"]:
        raise FormulaPolicyError("Active formula output unit or rounding policy differs from approved authority.")
    return formula
