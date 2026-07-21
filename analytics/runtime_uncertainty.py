"""Strict model-specific Product-v2 uncertainty contract validation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


class UncertaintyContractError(ValueError):
    pass


def validate_uncertainty_contract(value: Mapping[str, Any], repository_root: Path) -> None:
    schema = json.loads((repository_root / "config/runtime_uncertainty_contract.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(dict(value)), key=lambda error: list(error.path))
    if errors:
        raise UncertaintyContractError("invalid_uncertainty_contract")
    if value["forecastPresentationMode"] == "point_only":
        return
    provenance = value["calibrationProvenance"]
    bindings = {
        "modelId": "selectedModelId", "modelFamily": "modelFamily", "parameterSha256": "parameterSha256",
        "candidateRegistrySha256": "candidateRegistrySha256", "featureOrderSha256": "featureOrderSha256",
        "foldPlanSha256": "foldPlanSha256", "datasetId": "datasetId", "policyId": "policyId",
        "policyVersion": "policyVersion", "sourceFamily": "sourceFamily",
    }
    if any(provenance[left] != value[right] for left, right in bindings.items()) or value["lower"] > value["upper"]:
        raise UncertaintyContractError("calibration_identity_mismatch")
