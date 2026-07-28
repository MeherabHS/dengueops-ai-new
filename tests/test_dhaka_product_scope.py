from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from deployment_scope import DeploymentScopeError, load_product_scope, validate_product_scope  # noqa: E402


def test_governed_product_scope_is_dhaka_and_truthful() -> None:
    scope = load_product_scope()
    assert scope == {
        "schemaVersion": "1.0",
        "internalDeploymentId": "dhaka_south",
        "deploymentDisplayName": "Dhaka",
        "forecastDataCoverage": "synthetic_benchmark_dhaka_south_only",
        "evidenceScope": "synthetic_qualification",
        "operationalDhakaValidation": False,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("internalDeploymentId", "dhaka"),
        ("deploymentDisplayName", "Dhaka South"),
        ("forecastDataCoverage", "full_dhaka"),
        ("evidenceScope", "real_dhaka"),
        ("operationalDhakaValidation", True),
        ("schemaVersion", "2.0"),
    ],
)
def test_scope_tampering_fails_closed(field: str, value: object) -> None:
    scope = load_product_scope()
    scope[field] = value
    with pytest.raises(DeploymentScopeError):
        validate_product_scope(scope)


def test_missing_and_unexpected_scope_fields_fail_closed() -> None:
    scope = load_product_scope()
    missing = copy.deepcopy(scope)
    missing.pop("evidenceScope")
    unexpected = {**scope, "profileName": "legacy"}
    with pytest.raises(DeploymentScopeError):
        validate_product_scope(missing)
    with pytest.raises(DeploymentScopeError):
        validate_product_scope(unexpected)


def test_historical_profile_identity_and_geography_are_unchanged() -> None:
    profile_path = ROOT / "config" / "deployments" / "dhaka_south" / "profile.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert hashlib.sha256(profile_path.read_bytes()).hexdigest() == "53fe1fb09aea994c34a5b3d6839b60092c777030445b8ec46c32520675a7233a"
    assert profile["deployment_id"] == "dhaka_south"
    assert profile["geography"] == {"level": "city", "id": "BGD-DHAKA-SOUTH", "name": "Dhaka South"}
