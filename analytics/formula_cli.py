"""Trusted-host administration for governed formula data and proposals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from formula_policy import (
    FormulaPolicyError,
    load_formula_activation_policy,
    policy_raw_sha256,
    resolve_active_formula,
)
from formula_registry import (
    get_governed_formula,
    governed_registry_raw_sha256,
    load_governed_formula_registry,
)


def _print(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed formula administration (trusted host only).")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate-registry", "show-registry"):
        command = commands.add_parser(name)
        command.add_argument("--registry", type=Path)
    for name in ("show-policy", "verify-activation"):
        command = commands.add_parser(name)
        command.add_argument("--policy", type=Path)
    validate_formula = commands.add_parser("validate-formula")
    validate_formula.add_argument("formula_id")
    validate_formula.add_argument("--registry", type=Path)
    diff = commands.add_parser("diff-policy")
    diff.add_argument("left", type=Path)
    diff.add_argument("right", type=Path)
    proposal = commands.add_parser("prepare-activation")
    proposal.add_argument("formula_id")
    proposal.add_argument("--slot", default="inventory.gap")
    proposal.add_argument("--registry", type=Path)
    proposal.add_argument("--policy", type=Path)
    args = parser.parse_args()
    try:
        if args.command in {"validate-registry", "show-registry"}:
            registry = load_governed_formula_registry(args.registry) if args.registry else load_governed_formula_registry()
            _print({
                "ok": True,
                "registryVersion": registry["registryVersion"],
                "registrySha256": registry["registrySha256"],
                "registryRawSha256": governed_registry_raw_sha256(args.registry) if args.registry else governed_registry_raw_sha256(),
                "supportedFormulaSlots": registry["supportedFormulaSlots"],
                "formulaCount": len(registry["formulas"]),
            })
        elif args.command == "validate-formula":
            registry = load_governed_formula_registry(args.registry) if args.registry else load_governed_formula_registry()
            formula = get_governed_formula(args.formula_id, registry)
            _print({"ok": True, "formulaId": formula["formulaId"], "formulaSha256": formula["formulaSha256"], "status": formula["status"]})
        elif args.command == "show-policy":
            policy = load_formula_activation_policy(args.policy) if args.policy else load_formula_activation_policy()
            _print({
                "ok": True,
                "policyId": policy["policyId"],
                "policyVersion": policy["policyVersion"],
                "policySha256": policy["policySha256"],
                "policyRawSha256": policy_raw_sha256(args.policy) if args.policy else policy_raw_sha256(),
                "inventoryGapActivationStatus": policy["inventoryGapActivationStatus"],
                "authorityGateStatus": policy["authorityGate"]["status"],
            })
        elif args.command == "diff-policy":
            left, right = load_formula_activation_policy(args.left), load_formula_activation_policy(args.right)
            changed = sorted(key for key in set(left) | set(right) if left.get(key) != right.get(key))
            _print({"ok": True, "changedFields": changed, "changed": bool(changed)})
        elif args.command == "prepare-activation":
            policy = load_formula_activation_policy(args.policy) if args.policy else load_formula_activation_policy()
            registry = load_governed_formula_registry(args.registry) if args.registry else load_governed_formula_registry()
            formula = get_governed_formula(args.formula_id, registry)
            if formula["formulaSlot"] != args.slot or formula["status"] != "approved":
                raise FormulaPolicyError("Formula is not approved for the requested slot.")
            if policy["authorityGate"]["status"] != "approved" or any(
                value is None for key, value in policy["authorityGate"].items() if key != "status"
            ):
                raise FormulaPolicyError("formula_authority_gate_not_approved")
            _print({"ok": True, "proposal": {"formulaSlot": args.slot, "activeFormulaId": formula["formulaId"], "activeFormulaSha256": formula["formulaSha256"]}})
        else:
            policy = load_formula_activation_policy(args.policy) if args.policy else load_formula_activation_policy()
            formula = resolve_active_formula("inventory.gap", policy=policy)
            _print({"ok": True, "formulaId": formula["formulaId"], "formulaSha256": formula["formulaSha256"]})
        return 0
    except (ValueError, OSError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
