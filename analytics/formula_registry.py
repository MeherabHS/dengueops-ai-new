"""Versioned formula governance for the DengueOps research prototype."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "config" / "formulas.json"

DEPLOYMENT_GATES = (
    "benchmark_only",
    "research_candidate",
    "locally_backtested",
    "expert_reviewed",
    "institution_approved",
    "shadow_validated",
    "operational_advisory",
)
SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
SUPPORTED_FORMULA_VERSIONS = {"1.0", "1.1"}
KNOWN_CATEGORIES = {
    "standard_algorithmic", "direct_arithmetic", "data_derived_candidate",
    "locally_estimated_required", "institution_configured_required",
    "synthetic_benchmark_only", "unsupported_provisional",
    "deprecated_contradictory",
}
REQUIRED_FORMULA_FIELDS = {
    "formula_id", "version", "name", "category", "expression",
    "implementation_reference", "inputs", "output", "parameters",
    "configurable", "evidence_status", "evidence_references",
    "geographic_applicability", "local_estimation_required",
    "institutional_approval_required", "approval_status", "deployment_gate",
    "effective_date", "limitations", "test_fixture_ids",
}


class FormulaRegistryError(ValueError):
    """Raised when formula policy is invalid or a deployment gate is blocked."""


def load_formula_registry(path: str | Path = REGISTRY_PATH) -> dict[str, Any]:
    path = Path(path)
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormulaRegistryError(f"Formula registry is unreadable: {exc}") from exc
    validate_formula_registry(registry)
    return registry


def _validate_parameter(formula_id: str, name: str, parameter: Any, errors: list[str]) -> None:
    if not isinstance(parameter, dict):
        errors.append(f"{formula_id}.{name} must be an object.")
        return
    for key in ("value", "type", "unit"):
        if key not in parameter or parameter[key] in (None, ""):
            errors.append(f"{formula_id}.{name} requires {key}.")
    value, declared = parameter.get("value"), parameter.get("type")
    valid_type = {
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "string": isinstance(value, str),
        "integer_list": isinstance(value, list) and all(isinstance(v, int) and not isinstance(v, bool) for v in value),
    }.get(declared, False)
    if not valid_type:
        errors.append(f"{formula_id}.{name} value does not match type {declared!r}.")
        return
    values = value if isinstance(value, list) else [value]
    for item in values:
        if isinstance(item, (int, float)) and not isinstance(item, bool):
            if "min" in parameter and item < parameter["min"]:
                errors.append(f"{formula_id}.{name} is below its minimum.")
            if "max" in parameter and item > parameter["max"]:
                errors.append(f"{formula_id}.{name} exceeds its maximum.")


def validate_formula_registry(registry: dict[str, Any]) -> None:
    errors: list[str] = []
    if not isinstance(registry, dict):
        raise FormulaRegistryError("Formula registry must be a JSON object.")
    if registry.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append("Unsupported formula registry schema_version.")
    if not isinstance(registry.get("registry_version"), str) or not registry.get("registry_version"):
        errors.append("formula registry_version is required.")
    formulas = registry.get("formulas")
    if not isinstance(formulas, list) or not formulas:
        errors.append("Formula registry must contain a nonempty formulas array.")
        formulas = []
    seen: set[str] = set()
    for index, formula in enumerate(formulas):
        if not isinstance(formula, dict):
            errors.append(f"formulas[{index}] must be an object.")
            continue
        missing = REQUIRED_FORMULA_FIELDS - formula.keys()
        if missing:
            errors.append(f"formulas[{index}] missing fields: {sorted(missing)}.")
            continue
        formula_id = formula["formula_id"]
        if not isinstance(formula_id, str) or not formula_id:
            errors.append(f"formulas[{index}].formula_id must be nonempty.")
            continue
        if formula_id in seen:
            errors.append(f"Duplicate formula_id: {formula_id}.")
        seen.add(formula_id)
        if formula["version"] not in SUPPORTED_FORMULA_VERSIONS:
            errors.append(f"{formula_id} has unsupported version.")
        if formula["category"] not in KNOWN_CATEGORIES:
            errors.append(f"{formula_id} has unknown category.")
        gate = formula["deployment_gate"]
        if gate not in DEPLOYMENT_GATES:
            errors.append(f"{formula_id} has unknown deployment gate {gate!r}.")
            gate_index = -1
        else:
            gate_index = DEPLOYMENT_GATES.index(gate)
        if not isinstance(formula["inputs"], list) or any(not isinstance(v, dict) or not v.get("name") or not v.get("unit") for v in formula["inputs"]):
            errors.append(f"{formula_id} inputs require names and units.")
        if not isinstance(formula["output"], dict) or not formula["output"].get("name") or not formula["output"].get("unit"):
            errors.append(f"{formula_id} output requires name and unit.")
        if not isinstance(formula["parameters"], dict):
            errors.append(f"{formula_id} parameters must be an object.")
        else:
            for name, parameter in formula["parameters"].items():
                _validate_parameter(formula_id, name, parameter, errors)
        category = formula["category"]
        if category in {"unsupported_provisional", "synthetic_benchmark_only", "deprecated_contradictory"} and gate_index > DEPLOYMENT_GATES.index("research_candidate"):
            errors.append(f"{formula_id} unsupported/synthetic/deprecated formula exceeds research_candidate.")
        if formula["institutional_approval_required"] and formula["approval_status"] != "approved" and gate_index > DEPLOYMENT_GATES.index("research_candidate"):
            errors.append(f"{formula_id} institution-configured formula lacks approval for gate {gate}.")
        if category == "synthetic_benchmark_only" and gate != "benchmark_only":
            errors.append(f"{formula_id} synthetic benchmark formula must be benchmark_only.")
    if errors:
        raise FormulaRegistryError(" ".join(errors))


def get_formula(formula_id: str, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_formula_registry()
    for formula in registry["formulas"]:
        if formula["formula_id"] == formula_id:
            return formula
    raise FormulaRegistryError(f"Unknown formula_id: {formula_id}.")


def known_formula_ids(registry: dict[str, Any] | None = None) -> set[str]:
    """Return the identifiers in a validated registry without changing policy."""
    registry = registry or load_formula_registry()
    return {str(formula["formula_id"]) for formula in registry["formulas"]}


def formula_evidence_references(registry: dict[str, Any] | None = None) -> dict[str, tuple[str, ...]]:
    """Return formula-to-evidence links; registry values are evidence IDs."""
    registry = registry or load_formula_registry()
    return {
        str(formula["formula_id"]): tuple(str(value) for value in formula["evidence_references"])
        for formula in registry["formulas"]
    }


def effective_maximum_gate(formula_ids: list[str] | tuple[str, ...]) -> str:
    """Return the highest deployment gate allowed by every supplied formula."""
    if not formula_ids:
        raise FormulaRegistryError("At least one formula ID is required.")
    registry = load_formula_registry()
    gates = [get_formula(formula_id, registry)["deployment_gate"] for formula_id in formula_ids]
    return DEPLOYMENT_GATES[min(DEPLOYMENT_GATES.index(gate) for gate in gates)]


def get_parameter(formula_id: str, parameter_name: str) -> Any:
    formula = get_formula(formula_id)
    try:
        return formula["parameters"][parameter_name]["value"]
    except KeyError as exc:
        raise FormulaRegistryError(f"Unknown parameter {formula_id}.{parameter_name}.") from exc


def formula_gate_allows(formula_id: str, required_gate: str) -> bool:
    if required_gate not in DEPLOYMENT_GATES:
        raise FormulaRegistryError(f"Unknown required deployment gate: {required_gate}.")
    formula = get_formula(formula_id)
    return DEPLOYMENT_GATES.index(formula["deployment_gate"]) >= DEPLOYMENT_GATES.index(required_gate)


def registry_sha256(path: str | Path = REGISTRY_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def current_deployment_gate() -> str:
    gate = os.environ.get("DENGUEOPS_DEPLOYMENT_GATE", "benchmark_only")
    if gate not in DEPLOYMENT_GATES:
        raise FormulaRegistryError(f"Unknown deployment gate: {gate}.")
    return gate


def assert_not_benchmark_formula(formula_id: str) -> None:
    formula = get_formula(formula_id)
    if formula["category"] == "synthetic_benchmark_only":
        raise FormulaRegistryError(
            f"{formula_id} is synthetic_benchmark_only and cannot be loaded as an operational formula."
        )


def assert_formulas_allowed(formula_ids: list[str] | tuple[str, ...], required_gate: str) -> None:
    blockers = []
    for formula_id in formula_ids:
        formula = get_formula(formula_id)
        if not formula_gate_allows(formula_id, required_gate):
            blockers.append(
                f"{formula_id} (maximum gate={formula['deployment_gate']}, "
                f"evidence={formula['evidence_status']}, approval={formula['approval_status']})"
            )
    if blockers:
        raise FormulaRegistryError(
            f"Deployment gate '{required_gate}' is blocked by formula IDs: " + "; ".join(blockers)
        )


def build_formula_metadata(formula_ids: list[str] | tuple[str, ...], deployment_gate: str = "benchmark_only") -> dict[str, Any]:
    registry = load_formula_registry()
    unique_ids = list(dict.fromkeys(formula_ids))
    formulas = [get_formula(formula_id, registry) for formula_id in unique_ids]
    return {
        "formula_registry_version": registry["registry_version"],
        "formula_registry_sha256": registry_sha256(),
        "formula_ids_used": unique_ids,
        "deployment_gate": deployment_gate,
        "formula_validation_status": "governed_provisional",
        "formula_policy": {
            formula["formula_id"]: {
                "version": formula["version"],
                "name": formula["name"],
                "category": formula["category"],
                "evidence_status": formula["evidence_status"],
                "approval_status": formula["approval_status"],
                "deployment_gate": formula["deployment_gate"],
                "parameters": {name: value["value"] for name, value in formula["parameters"].items()},
            }
            for formula in formulas
        },
    }
