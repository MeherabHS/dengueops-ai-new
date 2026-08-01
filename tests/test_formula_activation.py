from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from formula_inputs import VARIABLE_CATALOG  # noqa: E402
from formula_policy import (  # noqa: E402
    FormulaPolicyError,
    canonical_policy_sha256,
    load_formula_activation_policy,
    resolve_active_formula,
    validate_formula_activation_policy,
)
from formula_registry import (  # noqa: E402
    FormulaRegistryError,
    get_governed_formula,
    governed_formula_sha256,
    governed_registry_sha256,
    load_governed_formula_registry,
    validate_governed_formula_registry,
)
from safe_formula import evaluate_formula_canonical  # noqa: E402


def approved_formula() -> dict:
    value = {
        "formulaId": "inventory.gap.fixture.v1",
        "formulaSlot": "inventory.gap",
        "formulaVersion": "1.0.0",
        "expression": "max(0, ceil(allocatedForecastCases * resourcePerCase) - availableResource)",
        "description": "Test-only governed formula fixture.",
        "inputs": [dict(item) for item in VARIABLE_CATALOG["inventory.gap"]],
        "outputUnit": "resource_units",
        "outputDomain": "nonnegative_integer",
        "roundingPolicy": "ceiling_to_integer",
        "status": "approved",
        "scientificLimitations": ["Test fixture only."],
        "formulaSha256": "",
    }
    value["formulaSha256"] = governed_formula_sha256(value)
    return value


def registry_with(formula: dict) -> dict:
    value = {
        "schemaVersion": "1.0",
        "registryVersion": "b8.5-v1",
        "registrySha256": "",
        "supportedFormulaSlots": ["inventory.gap"],
        "formulas": [formula],
    }
    value["registrySha256"] = governed_registry_sha256(value)
    return value


def registry_with_all(*formulas: dict) -> dict:
    value = registry_with(formulas[0])
    value["formulas"] = list(formulas)
    value["registrySha256"] = governed_registry_sha256(value)
    return value


def approved_policy(formula: dict) -> dict:
    value = copy.deepcopy(load_formula_activation_policy())
    value["formulaBindings"] = {
        "inventory.gap": {
            "activeFormulaId": formula["formulaId"],
            "activeFormulaSha256": formula["formulaSha256"],
        }
    }
    value["inventoryGapActivationStatus"] = "configured"
    value["authorityGate"] = {
        "status": "approved",
        "resourceType": "test_resource",
        "resourceUnit": "resource_units",
        "resourcePerCase": "1.000000",
        "coefficientSourceReferenceId": "test-fixture",
        "coefficientHorizon": "two_weeks",
        "allocationPolicyId": "test-allocation",
        "allocationApprovalReferenceId": "test-approval",
        "roundingRule": "ceiling_to_integer",
        "approvedInventoryId": "test-inventory",
        "formulaActivationApprovalReferenceId": "test-formula-approval",
    }
    value["policySha256"] = canonical_policy_sha256(value)
    return value


def test_production_registry_and_policy_activate_only_operational_formula() -> None:
    registry, policy = load_governed_formula_registry(), load_formula_activation_policy()
    assert [formula["formulaId"] for formula in registry["formulas"]] == [
        "inventory.gap.synthetic-qualification.v1",
        "inventory.gap.operational.v1",
    ]
    assert policy["formulaBindings"]["inventory.gap"]["activeFormulaId"] == "inventory.gap.operational.v1"
    assert policy["inventoryGapActivationStatus"] == "configured"
    assert policy["authorityGate"]["status"] == "approved"
    assert resolve_active_formula("inventory.gap", policy=policy, registry=registry)["formulaId"] == "inventory.gap.operational.v1"


def test_explicit_approved_id_sha_binding_can_resolve_fixture() -> None:
    formula = approved_formula()
    assert resolve_active_formula("inventory.gap", policy=approved_policy(formula), registry=registry_with(formula)) == formula


def test_registered_formula_never_activates_itself() -> None:
    formula = approved_formula()
    policy = copy.deepcopy(load_formula_activation_policy())
    policy["formulaBindings"] = {}
    policy["inventoryGapActivationStatus"] = "not_configured"
    policy["authorityGate"] = {key: ("not_approved" if key == "status" else None) for key in policy["authorityGate"]}
    policy["policySha256"] = canonical_policy_sha256(policy)
    with pytest.raises(FormulaPolicyError, match="formula_not_configured"):
        resolve_active_formula("inventory.gap", policy=policy, registry=registry_with(formula))


def test_wrong_sha_tampered_expression_inactive_and_old_sha_fail_closed() -> None:
    formula = approved_formula()
    wrong_sha = copy.deepcopy(formula)
    wrong_sha["formulaSha256"] = "0" * 64
    with pytest.raises(FormulaRegistryError, match="hash mismatch"):
        validate_governed_formula_registry(registry_with(wrong_sha))

    tampered = copy.deepcopy(formula)
    tampered["expression"] = "0"
    with pytest.raises(FormulaRegistryError, match="hash mismatch"):
        validate_governed_formula_registry(registry_with(tampered))

    inactive = copy.deepcopy(formula)
    inactive["status"] = "draft"
    inactive["formulaSha256"] = governed_formula_sha256(inactive)
    with pytest.raises(FormulaPolicyError, match="not approved"):
        resolve_active_formula("inventory.gap", policy=approved_policy(inactive), registry=registry_with(inactive))

    old_binding = approved_policy(formula)
    changed = copy.deepcopy(formula)
    changed["expression"] = "max(0, availableResource)"
    changed["formulaSha256"] = governed_formula_sha256(changed)
    with pytest.raises(FormulaPolicyError, match="binding mismatch"):
        resolve_active_formula("inventory.gap", policy=old_binding, registry=registry_with(changed))


def test_duplicate_variable_and_policy_tampering_fail_closed() -> None:
    formula = approved_formula()
    formula["inputs"].append(copy.deepcopy(formula["inputs"][0]))
    formula["formulaSha256"] = governed_formula_sha256(formula)
    with pytest.raises((FormulaRegistryError, ValueError)):
        validate_governed_formula_registry(registry_with(formula))
    policy = load_formula_activation_policy()
    policy["formulaBindings"] = {}
    policy["policySha256"] = canonical_policy_sha256(policy)
    with pytest.raises(FormulaPolicyError, match="inconsistent"):
        validate_formula_activation_policy(policy)


def test_registry_raw_identity_changes_with_bytes(tmp_path: Path) -> None:
    source = ROOT / "config" / "inventory_gap_formulas.json"
    copied = tmp_path / "registry.json"
    copied.write_bytes(source.read_bytes() + b" ")
    assert copied.read_bytes() != source.read_bytes()
    assert load_governed_formula_registry(source) == json.loads(source.read_text(encoding="utf-8"))


def test_data_only_formula_registration_and_policy_change_affect_only_future_evaluations() -> None:
    formula_a = approved_formula()
    formula_b = copy.deepcopy(formula_a)
    formula_b.update(
        formulaId="inventory.gap.fixture.v2",
        formulaVersion="2.0.0",
        expression="max(0, ceil(allocatedForecastCases * resourcePerCase - availableResource + 1))",
        description="Second test-only governed expression using the unchanged variable catalog.",
        formulaSha256="",
    )
    formula_b["formulaSha256"] = governed_formula_sha256(formula_b)
    registry = registry_with_all(formula_a, formula_b)

    # Registration is entirely governed JSON data: both expressions validate
    # against the existing application-code variable catalog.
    validated = validate_governed_formula_registry(registry)
    assert [item["formulaId"] for item in validated["formulas"]] == [
        formula_a["formulaId"],
        formula_b["formulaId"],
    ]

    # Adding formula B does not change the binding to formula A.
    policy_a = approved_policy(formula_a)
    resolved_a = resolve_active_formula("inventory.gap", policy=policy_a, registry=validated)
    inputs = {
        "allocatedForecastCases": "10.25",
        "resourcePerCase": "1",
        "availableResource": 10,
    }
    result_a = evaluate_formula_canonical(
        resolved_a["expression"],
        inputs,
        allowed_variables={item["name"] for item in resolved_a["inputs"]},
    )
    assert result_a == "1"
    assert resolve_active_formula("inventory.gap", policy=policy_a, registry=validated)["formulaId"] == formula_a["formulaId"]

    # Only an explicit future policy binding by formula ID + SHA selects B.
    policy_b = approved_policy(formula_b)
    resolved_b = resolve_active_formula("inventory.gap", policy=policy_b, registry=validated)
    result_b = evaluate_formula_canonical(
        resolved_b["expression"],
        inputs,
        allowed_variables={item["name"] for item in resolved_b["inputs"]},
    )
    assert result_b == "2"

    # The prior resolved formula/version and its SHA remain independently
    # verifiable and produce the original result.
    prior = get_governed_formula(formula_a["formulaId"], validated)
    assert governed_formula_sha256(prior) == formula_a["formulaSha256"]
    assert evaluate_formula_canonical(
        prior["expression"],
        inputs,
        allowed_variables={item["name"] for item in prior["inputs"]},
    ) == result_a
