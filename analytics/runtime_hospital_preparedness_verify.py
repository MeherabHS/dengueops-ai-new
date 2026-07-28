"""Reopen and verify immutable synthetic preparedness qualification packages."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from formula_policy import validate_qualification_formula_policy
from formula_registry import validate_governed_formula_registry
from formula_inputs import allowed_variable_names
from hospital_capacity_reference import validate_capacity_reference
from hospital_inventory import validate_inventory
from runtime_hospital_preparedness import _allocate_cases
from runtime_forecast_outcome_source import verify_forecast_source
from safe_formula import evaluate_formula_canonical
from synthetic_hospital_inventory import validate_scenario_policy, validate_synthetic_inventory

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_SCHEMA = ROOT / "config" / "runtime_hospital_preparedness.schema.json"
COMMIT_SCHEMA = ROOT / "config" / "runtime_hospital_preparedness_commit.schema.json"
LATEST_SCHEMA = ROOT / "config" / "runtime_hospital_preparedness_latest.schema.json"
UUID = re.compile(r"^[a-f0-9-]{36}$")


class HospitalPreparednessVerificationError(ValueError):
    """Raised when qualification evidence or its pointer fails closed."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HospitalPreparednessVerificationError("Qualification JSON is unreadable.") from exc
    if not isinstance(value, dict):
        raise HospitalPreparednessVerificationError("Qualification JSON must be an object.")
    return value


def _schema(value: dict[str, Any], path: Path) -> None:
    schema = _json(path)
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(value),
        key=lambda error: list(error.path),
    )
    if errors:
        raise HospitalPreparednessVerificationError(f"Qualification schema failure: {errors[0].message}")


def verify_qualification(runtime_root: str | Path, preparedness_id: str) -> dict[str, Any]:
    root = Path(runtime_root).resolve()
    if not UUID.fullmatch(preparedness_id):
        raise HospitalPreparednessVerificationError("Invalid preparedness ID.")
    package = (root / "hospital-preparedness-qualification" / preparedness_id).resolve()
    if root not in package.parents:
        raise HospitalPreparednessVerificationError("Qualification path escaped runtime root.")
    commit_path = package / "metadata" / "commit.json"
    commit = _json(commit_path)
    _schema(commit, COMMIT_SCHEMA)
    if commit["preparednessId"] != preparedness_id or commit["evidenceScope"] != "synthetic_qualification":
        raise HospitalPreparednessVerificationError("Qualification commit identity mismatch.")
    artifact_root = package / "artifacts"
    if set(commit["artifactHashes"]) != {path.name for path in artifact_root.iterdir() if path.is_file()}:
        raise HospitalPreparednessVerificationError("Qualification artifact set mismatch.")
    for name, digest in commit["artifactHashes"].items():
        if _sha(artifact_root / name) != digest:
            raise HospitalPreparednessVerificationError("Qualification artifact hash mismatch.")
    evidence = _json(artifact_root / "preparedness_evidence.json")
    _schema(evidence, EVIDENCE_SCHEMA)
    if evidence["preparednessId"] != preparedness_id or evidence["scenarioId"] != commit["scenarioId"]:
        raise HospitalPreparednessVerificationError("Qualification evidence identity mismatch.")
    capacity = validate_capacity_reference(_json(artifact_root / "official_capacity_reference_snapshot.json"))
    validate_inventory(_json(artifact_root / "official_hospital_inventory_snapshot.json"))
    scenario_policy = validate_scenario_policy(_json(artifact_root / "synthetic_scenario_policy_snapshot.json"))
    synthetic = validate_synthetic_inventory(
        _json(artifact_root / "synthetic_inventory_snapshot.json"),
        reference=capacity,
        policy=scenario_policy,
    )
    validate_governed_formula_registry(_json(artifact_root / "formula_registry_snapshot.json"))
    validate_qualification_formula_policy(
        _json(artifact_root / "formula_activation_policy_snapshot.json"),
        scenario_policy=scenario_policy,
    )
    formula = _json(artifact_root / "formula_snapshot.json")
    binding = evidence["authorityBindings"]
    if (formula.get("formulaId"), formula.get("formulaSha256")) != (binding["formulaId"], binding["formulaSha256"]):
        raise HospitalPreparednessVerificationError("Qualification formula snapshot mismatch.")
    source = verify_forecast_source(
        root, commit["forecastRunId"], commit["forecastCommitSha256"], {"quick_forecast_p1", "quick_forecast_p2"}
    )
    if source["commit"] != _json(artifact_root / "forecast_commit_snapshot.json"):
        raise HospitalPreparednessVerificationError("Forecast commit snapshot mismatch.")
    if source["forecast"] != _json(artifact_root / "forecast_output_snapshot.json"):
        raise HospitalPreparednessVerificationError("Forecast output snapshot mismatch.")
    if source["uncertainty"] != _json(artifact_root / "forecast_uncertainty_snapshot.json"):
        raise HospitalPreparednessVerificationError("Forecast uncertainty snapshot mismatch.")
    scenario = next(item for item in synthetic["scenarios"] if item["scenarioId"] == commit["scenarioId"])
    expected_allocations = _allocate_cases(source["forecast"]["forecastReported"], scenario["hospitals"])
    synthetic_rows = {item["hospitalId"]: item for item in scenario["hospitals"]}
    for row in evidence["hospitals"]:
        source_row = synthetic_rows[row["hospitalId"]]
        if source_row["allocationStatus"] != "configured":
            if row["status"] != source_row["resultStatus"] or row["syntheticGap"] is not None:
                raise HospitalPreparednessVerificationError("Non-calculated qualification status mismatch.")
            continue
        allocated = expected_allocations[row["hospitalId"]]
        expected_gap = evaluate_formula_canonical(
            formula["expression"],
            {
                "allocatedForecastCases": allocated,
                "resourcePerCase": scenario_policy["coefficient"]["resourcePerCase"],
                "availableResource": source_row["quantity"],
            },
            allowed_variables=allowed_variable_names("inventory.gap"),
        )
        if (
            row["allocatedForecastCases"] != allocated
            or row["availableResource"] != source_row["quantity"]
            or row["syntheticGap"] != expected_gap
        ):
            raise HospitalPreparednessVerificationError("Calculated qualification result mismatch.")
    return {
        "commit": commit,
        "evidence": evidence,
        "artifactHashes": commit["artifactHashes"],
        "commitSha256": _sha(commit_path),
    }


def verify_latest_qualification(runtime_root: str | Path) -> dict[str, Any]:
    root = Path(runtime_root).resolve()
    latest = root / "deployments" / "dhaka_south" / "hospital-preparedness-qualification" / "latest.json"
    pointer = _json(latest)
    _schema(pointer, LATEST_SCHEMA)
    verified = verify_qualification(root, pointer["preparednessId"])
    if pointer["commitSha256"] != verified["commitSha256"]:
        raise HospitalPreparednessVerificationError("Qualification pointer commit hash mismatch.")
    if pointer["evidenceSha256"] != verified["artifactHashes"]["preparedness_evidence.json"]:
        raise HospitalPreparednessVerificationError("Qualification pointer evidence hash mismatch.")
    return {"pointer": pointer, **verified}


def list_qualifications(runtime_root: str | Path) -> list[str]:
    root = Path(runtime_root).resolve()
    authority = root / "hospital-preparedness-qualification"
    if not authority.exists():
        return []
    result = []
    for path in authority.iterdir():
        if path.is_dir() and UUID.fullmatch(path.name):
            verify_qualification(root, path.name)
            result.append(path.name)
    return sorted(result)
