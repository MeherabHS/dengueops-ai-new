from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from formula_policy import (  # noqa: E402
    FormulaPolicyError,
    canonical_policy_sha256,
    load_formula_activation_policy,
    load_qualification_formula_policy,
    resolve_qualification_formula,
)
from formula_registry import governed_formula_sha256, governed_registry_sha256, load_governed_formula_registry  # noqa: E402


def test_qualification_formula_identity_is_preserved_but_not_operationally_activated() -> None:
    registry = load_governed_formula_registry()
    formula = registry["formulas"][0]
    assert formula["formulaId"] == "inventory.gap.synthetic-qualification.v1"
    assert formula["outputUnit"] == "bed_units"
    activation = load_formula_activation_policy()
    assert activation["inventoryGapActivationStatus"] == "configured"
    assert activation["formulaBindings"]["inventory.gap"]["activeFormulaId"] == "inventory.gap.operational.v1"
    assert resolve_qualification_formula(
        "inventory.gap", requested_evidence_scope="synthetic_qualification"
    )["formulaSha256"] == formula["formulaSha256"]


def test_operational_scope_rejects_synthetic_policy() -> None:
    for scope in ("operational", "official_capacity_reference"):
        with pytest.raises(FormulaPolicyError, match="formula_scope_mismatch"):
            resolve_qualification_formula("inventory.gap", requested_evidence_scope=scope)


def test_changed_formula_requires_new_id_sha_policy_binding() -> None:
    registry = load_governed_formula_registry()
    changed_registry = copy.deepcopy(registry)
    formula = changed_registry["formulas"][0]
    formula["formulaId"] = "inventory.gap.synthetic-qualification.v2"
    formula["formulaVersion"] = "2.0.0"
    formula["expression"] = "max(0, availableResource)"
    formula["formulaSha256"] = governed_formula_sha256(formula)
    changed_registry["registrySha256"] = governed_registry_sha256(changed_registry)
    old_policy = load_qualification_formula_policy()
    with pytest.raises(FormulaPolicyError, match="not registered|binding mismatch"):
        resolve_qualification_formula(
            "inventory.gap",
            requested_evidence_scope="synthetic_qualification",
            policy=old_policy,
            registry=changed_registry,
        )
    new_policy = copy.deepcopy(old_policy)
    new_policy["formulaBindings"]["inventory.gap"]["activeFormulaId"] = formula["formulaId"]
    new_policy["formulaBindings"]["inventory.gap"]["activeFormulaSha256"] = formula["formulaSha256"]
    new_policy["policySha256"] = canonical_policy_sha256(new_policy)
    assert resolve_qualification_formula(
        "inventory.gap",
        requested_evidence_scope="synthetic_qualification",
        policy=new_policy,
        registry=changed_registry,
    )["expression"] == formula["expression"]
