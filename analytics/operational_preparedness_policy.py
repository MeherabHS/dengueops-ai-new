"""Governed operational-preparedness planning policy."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config" / "deployments" / "dhaka_south" / "operational_preparedness_policy.json"
SCHEMA_PATH = ROOT / "config" / "operational_preparedness_policy.schema.json"


class OperationalPreparednessPolicyError(ValueError):
    pass


def canonical_sha256(value: dict[str, Any], excluded: frozenset[str] = frozenset()) -> str:
    payload = json.dumps({k: v for k, v in value.items() if k not in excluded}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_operational_preparedness_policy(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path or os.environ.get("DENGUEOPS_OPERATIONAL_PLANNING_POLICY_PATH", str(DEFAULT_PATH)))
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperationalPreparednessPolicyError("Operational planning policy is unreadable.") from exc
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        raise OperationalPreparednessPolicyError(f"Operational planning policy failed schema validation: {errors[0].message}")
    if value["policySha256"] != canonical_sha256(value, frozenset({"policySha256"})):
        raise OperationalPreparednessPolicyError("Operational planning policy hash mismatch.")
    return value
