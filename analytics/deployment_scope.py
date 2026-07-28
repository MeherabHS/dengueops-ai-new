"""Fail-closed loader for current product-scope authority."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "config" / "deployment_product_scope.schema.json"
EXPECTED = {
    "schemaVersion": "1.0",
    "internalDeploymentId": "dhaka_south",
    "deploymentDisplayName": "Dhaka",
    "forecastDataCoverage": "synthetic_benchmark_dhaka_south_only",
    "evidenceScope": "synthetic_qualification",
    "operationalDhakaValidation": False,
}


class DeploymentScopeError(ValueError):
    """Raised when product-scope authority is missing or inconsistent."""


def product_scope_path(deployment_id: str = "dhaka_south") -> Path:
    if deployment_id != "dhaka_south":
        raise DeploymentScopeError("Unsupported internal deployment ID.")
    return ROOT / "config" / "deployments" / deployment_id / "product_scope.json"


def validate_product_scope(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DeploymentScopeError("Product scope must be a JSON object.")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise DeploymentScopeError(f"Product scope failed schema validation: {errors[0].message}")
    if value != EXPECTED:
        raise DeploymentScopeError("Product scope does not match governed Dhaka authority.")
    return dict(value)


def load_product_scope(
    deployment_id: str = "dhaka_south",
    path: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(path) if path is not None else product_scope_path(deployment_id)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeploymentScopeError("Product scope is unreadable.") from exc
    return validate_product_scope(value)
