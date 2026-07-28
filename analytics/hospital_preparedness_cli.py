"""Trusted-host administration for hospital research and synthetic qualification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from dhaka_hospital_research import (
    classify_registry_rows,
    fetch_official_registry_pages,
    load_coverage,
)
from formula_policy import load_formula_activation_policy, load_qualification_formula_policy
from hospital_capacity_reference import load_capacity_reference, raw_sha256
from runtime_hospital_preparedness_commit import publish_qualification
from runtime_hospital_preparedness_verify import (
    list_qualifications,
    verify_latest_qualification,
    verify_qualification,
)
from synthetic_hospital_inventory import (
    load_scenario_policy,
    load_synthetic_inventory,
    write_synthetic_inventory,
)


def _print(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Synthetic hospital-preparedness qualification (trusted host only).")
    parser.add_argument("--runtime-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    research = commands.add_parser("research-official-hospitals")
    research.add_argument("--live", action="store_true")
    commands.add_parser("verify-capacity-reference")
    generated = commands.add_parser("generate-synthetic-inventory")
    generated.add_argument("--output", type=Path)
    diff = commands.add_parser("diff-synthetic-inventory")
    diff.add_argument("left", type=Path)
    diff.add_argument("right", type=Path)
    commands.add_parser("validate-qualification-authority")
    create = commands.add_parser("generate-qualification")
    create.add_argument("scenario_id", choices=["baseline_availability", "constrained_availability", "severe_constraint"])
    create.add_argument("--preparedness-id")
    verify = commands.add_parser("verify-qualification")
    verify.add_argument("--preparedness-id")
    show = commands.add_parser("show-qualification")
    show.add_argument("--preparedness-id")
    commands.add_parser("list-qualifications")
    args = parser.parse_args()
    try:
        if args.command == "research-official-hospitals":
            if args.live:
                rows = fetch_official_registry_pages()
                classified = classify_registry_rows(rows)
                _print({"ok": True, "officialRows": len(rows), **{key: len(value) for key, value in classified.items()}})
            else:
                coverage = load_coverage()
                _print({
                    "ok": True,
                    "coverageId": coverage["coverageId"],
                    "officialRecordsReviewed": coverage["totalOfficialRecordsReviewed"],
                    "includedHospitals": len(coverage["includedHospitals"]),
                    "excludedFacilities": len(coverage["excludedFacilities"]),
                    "unresolvedFacilities": len(coverage["unresolvedFacilities"]),
                })
        elif args.command == "verify-capacity-reference":
            value = load_capacity_reference()
            _print({
                "ok": True,
                "capacityReferenceId": value["capacityReferenceId"],
                "hospitalCount": len(value["hospitals"]),
                "canonicalSha256": value["capacityReferenceCanonicalSha256"],
                "rawSha256": raw_sha256(),
            })
        elif args.command == "generate-synthetic-inventory":
            value = write_synthetic_inventory(args.output) if args.output else write_synthetic_inventory()
            _print({"ok": True, "syntheticInventoryId": value["syntheticInventoryId"], "sha256": value["syntheticInventorySha256"]})
        elif args.command == "diff-synthetic-inventory":
            left = load_synthetic_inventory(args.left)
            right = load_synthetic_inventory(args.right)
            _print({
                "ok": True,
                "leftId": left["syntheticInventoryId"],
                "rightId": right["syntheticInventoryId"],
                "identical": left == right,
                "leftSha256": left["syntheticInventorySha256"],
                "rightSha256": right["syntheticInventorySha256"],
            })
        elif args.command == "validate-qualification-authority":
            production = load_formula_activation_policy()
            qualification = load_qualification_formula_policy()
            scenario = load_scenario_policy()
            synthetic = load_synthetic_inventory()
            _print({
                "ok": True,
                "productionFormulaStatus": production["inventoryGapActivationStatus"],
                "qualificationPolicySha256": qualification["policySha256"],
                "scenarioPolicySha256": scenario["policySha256"],
                "syntheticInventorySha256": synthetic["syntheticInventorySha256"],
            })
        else:
            if args.runtime_root is None or not args.runtime_root.is_absolute():
                raise ValueError("This command requires an absolute --runtime-root.")
            if args.command == "generate-qualification":
                _print({"ok": True, **publish_qualification(
                    args.runtime_root, args.scenario_id, preparedness_id=args.preparedness_id
                )})
            elif args.command in {"verify-qualification", "show-qualification"}:
                value = (
                    verify_qualification(args.runtime_root, args.preparedness_id)
                    if args.preparedness_id
                    else verify_latest_qualification(args.runtime_root)
                )
                if args.command == "show-qualification":
                    evidence = value["evidence"]
                    _print({
                        "ok": True,
                        "preparednessId": evidence["preparednessId"],
                        "scenarioId": evidence["scenarioId"],
                        "evidenceScope": evidence["evidenceScope"],
                        "hospitalStatusCounts": {
                            status: sum(1 for row in evidence["hospitals"] if row["status"] == status)
                            for status in sorted({row["status"] for row in evidence["hospitals"]})
                        },
                    })
                else:
                    _print({"ok": True, "preparednessId": value["evidence"]["preparednessId"], "commitSha256": value["commitSha256"]})
            else:
                _print({"ok": True, "preparednessIds": list_qualifications(args.runtime_root)})
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
