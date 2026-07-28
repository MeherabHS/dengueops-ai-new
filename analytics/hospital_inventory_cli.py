"""Trusted-host CLI for append-only hospital inventory administration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hospital_inventory import SEED_PATH, inventory_diff, load_inventory
from runtime_hospital_inventory_commit import activate_inventory, import_inventory
from runtime_hospital_inventory_verify import (
    list_inventory_versions,
    verify_active_inventory,
    verify_inventory_version,
)


def _print(value: Any) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str))


def main() -> int:
    parser = argparse.ArgumentParser(description="Governed hospital inventory administration (trusted host only).")
    parser.add_argument("--runtime-root", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("path", type=Path, nargs="?", default=SEED_PATH)
    show = commands.add_parser("show")
    show.add_argument("path", type=Path, nargs="?", default=SEED_PATH)
    diff = commands.add_parser("diff")
    diff.add_argument("left", type=Path)
    diff.add_argument("right", type=Path)
    imported = commands.add_parser("import")
    imported.add_argument("path", type=Path)
    imported.add_argument("--operator", required=True)
    imported.add_argument("--reason", required=True)
    for name in ("activate", "rollback"):
        command = commands.add_parser(name)
        command.add_argument("inventory_id")
        command.add_argument("--operator", required=True)
        command.add_argument("--reason", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--inventory-id")
    commands.add_parser("list-versions")
    args = parser.parse_args()
    try:
        if args.command in {"validate", "show"}:
            inventory = load_inventory(args.path)
            _print({
                "ok": True,
                "inventoryId": inventory["inventoryId"],
                "inventoryVersion": inventory["inventoryVersion"],
                "hospitalCount": len(inventory["hospitals"]),
                "verificationStatus": inventory["verificationStatus"],
                "allocationStatus": inventory["allocationStatus"],
            })
        elif args.command == "diff":
            _print({"ok": True, **inventory_diff(load_inventory(args.left), load_inventory(args.right))})
        else:
            if args.runtime_root is None or not args.runtime_root.is_absolute():
                raise ValueError("This command requires an absolute --runtime-root.")
            if args.command == "import":
                _print({"ok": True, **import_inventory(args.runtime_root, args.path, operator_identifier=args.operator, change_reason=args.reason)})
            elif args.command in {"activate", "rollback"}:
                reason = args.reason if args.command == "activate" else f"Rollback: {args.reason}"
                pointer = activate_inventory(args.runtime_root, args.inventory_id, operator_identifier=args.operator, activation_reason=reason)
                _print({"ok": True, "rollback": args.command == "rollback", "pointer": pointer})
            elif args.command == "verify":
                verified = verify_inventory_version(args.runtime_root, args.inventory_id) if args.inventory_id else verify_active_inventory(args.runtime_root)
                _print({"ok": True, "inventoryId": verified["inventory"]["inventoryId"], "inventoryArtifactSha256": verified["inventoryArtifactSha256"], "inventoryCommitSha256": verified["inventoryCommitSha256"]})
            else:
                _print({"ok": True, "inventoryIds": list_inventory_versions(args.runtime_root)})
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        _print({"ok": False, "error": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
