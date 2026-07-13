"""Manifest-bound provenance helpers for DengueOps analytical artifacts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_PATH = ROOT / "data" / "input_manifest.json"
SUPPORTED_MANIFEST_SCHEMAS = {"1.0"}

PROVENANCE_COLUMNS = [
    "input_run_id",
    "manifest_sha256",
    "case_source",
    "climate_source",
]


class ProvenanceError(ValueError):
    """Raised when manifest or artifact provenance is missing or inconsistent."""


def sha256_file(path: str | Path) -> str:
    path = Path(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_manifest_reference(path_value: str, manifest_path: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    # Canonical manifests use repository-relative paths. Temporary test manifests
    # may instead reference siblings, so prefer ROOT only when the path exists.
    root_candidate = ROOT / path
    return root_candidate if root_candidate.exists() else manifest_path.parent / path


def load_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> tuple[dict[str, Any], str]:
    path = Path(path)
    if not path.exists():
        raise ProvenanceError(f"Input manifest does not exist: {path}")
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ProvenanceError(f"Input manifest is unreadable: {exc}") from exc
    if not isinstance(manifest, dict):
        raise ProvenanceError("Input manifest must be a JSON object.")
    schema = str(manifest.get("schema_version", ""))
    if schema not in SUPPORTED_MANIFEST_SCHEMAS:
        raise ProvenanceError(f"Unsupported input manifest schema: {schema or '<missing>'}")
    if not str(manifest.get("run_id", "")).strip():
        raise ProvenanceError("Input manifest run_id is missing.")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or any(domain not in inputs for domain in ("cases", "climate", "operational")):
        raise ProvenanceError("Input manifest must describe cases, climate, and operational inputs.")
    cross = manifest.get("cross_source_validation", {})
    if cross.get("status") != "passed":
        raise ProvenanceError("Input manifest cross-source validation status is not passed.")
    return manifest, hashlib.sha256(raw).hexdigest()


def verify_manifest_inputs(manifest: Mapping[str, Any], manifest_path: str | Path = DEFAULT_MANIFEST_PATH) -> None:
    manifest_path = Path(manifest_path)
    errors: list[str] = []
    for domain, entry in manifest.get("inputs", {}).items():
        for file_entry in entry.get("files", []):
            display_path = str(file_entry.get("path", ""))
            expected = str(file_entry.get("sha256", ""))
            actual_path = _resolve_manifest_reference(display_path, manifest_path)
            if not actual_path.exists():
                errors.append(f"{domain} input is missing: {display_path}")
            elif not expected:
                errors.append(f"{domain} input hash is missing for {display_path}")
            elif sha256_file(actual_path) != expected:
                errors.append(f"{domain} input hash differs from manifest: {display_path}")
    if errors:
        raise ProvenanceError("; ".join(errors))


def build_compact_provenance(
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    inputs = manifest["inputs"]
    cases = inputs["cases"]
    climate = inputs["climate"]
    operational = inputs["operational"]
    geography = cases.get("geography") or {}
    try:
        display_path = Path(manifest_path).resolve().relative_to(ROOT).as_posix()
    except ValueError:
        display_path = str(Path(manifest_path).resolve())
    result = {
        "run_id": str(manifest["run_id"]),
        "manifest_path": display_path,
        "manifest_sha256": manifest_sha256,
        "case_source": str(cases.get("detected_source") or cases.get("selected_source")),
        "climate_source": str(climate.get("detected_source") or climate.get("selected_source")),
        "operational_source": str(operational.get("detected_source") or operational.get("selected_source")),
        "source_classes": {
            "cases": str(cases.get("source_class", "")),
            "climate": str(climate.get("source_class", "")),
            "operational": str(operational.get("source_class", "")),
        },
        "forecast_geography": {
            "level": str(geography.get("level", "")),
            "id": str(geography.get("id", "")),
            "name": str(geography.get("name", "")),
        },
        "validation_status": str(manifest.get("cross_source_validation", {}).get("status", "")),
        "warnings": list(manifest.get("warnings", [])),
        "overrides": list(manifest.get("overrides", [])),
    }
    governance = manifest.get("governance")
    if governance is not None:
        if not isinstance(governance, dict):
            raise ProvenanceError("Input manifest governance must be an object.")
        required = {
            "deployment_profile_id", "deployment_profile_schema_version",
            "deployment_profile_sha256", "deployment_profile_status",
            "deployment_profile_data_mode", "observed_data_mode",
            "evidence_registry_schema_version", "evidence_registry_version",
            "evidence_registry_sha256", "formula_registry_version",
            "formula_registry_sha256", "model_card_id", "model_card_version",
            "candidate_registry_sha256", "active_model_id", "active_model_parameters_sha256",
            "adoption_status", "adoption_policy_version", "uncertainty_method_id",
            "uncertainty_method_version", "uncertainty_status",
        }
        missing = required - governance.keys()
        if missing:
            raise ProvenanceError(f"Input manifest governance is missing: {sorted(missing)}")
        result.update({key: governance[key] for key in sorted(required)})
    return result


def load_compact_provenance(
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
    *,
    verify_inputs: bool = True,
) -> dict[str, Any]:
    manifest, digest = load_manifest(manifest_path)
    if verify_inputs:
        verify_manifest_inputs(manifest, manifest_path)
    return build_compact_provenance(manifest, digest, manifest_path)


def add_feature_provenance(df: pd.DataFrame, provenance: Mapping[str, Any]) -> pd.DataFrame:
    out = df.copy()
    out["input_run_id"] = provenance["run_id"]
    out["manifest_sha256"] = provenance["manifest_sha256"]
    out["case_source"] = provenance["case_source"]
    out["climate_source"] = provenance["climate_source"]
    return out


def provenance_from_feature_frame(
    df: pd.DataFrame,
    manifest_path: str | Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    missing = set(PROVENANCE_COLUMNS) - set(df.columns)
    if missing:
        raise ProvenanceError(f"Feature matrix missing provenance columns: {sorted(missing)}")
    values: dict[str, str] = {}
    for column in PROVENANCE_COLUMNS:
        series = df[column]
        if series.isna().any():
            raise ProvenanceError(f"Feature provenance column {column} contains null values.")
        unique = series.astype(str).unique()
        if len(unique) != 1 or not unique[0].strip():
            raise ProvenanceError(f"Feature provenance column {column} must contain one nonempty value.")
        values[column] = unique[0]
    provenance = load_compact_provenance(manifest_path)
    expected = {
        "input_run_id": provenance["run_id"],
        "manifest_sha256": provenance["manifest_sha256"],
        "case_source": provenance["case_source"],
        "climate_source": provenance["climate_source"],
    }
    if values != expected:
        raise ProvenanceError("Feature provenance does not match the current input manifest.")
    return provenance


def assert_same_provenance(*items: Mapping[str, Any], labels: Sequence[str] | None = None) -> dict[str, Any]:
    if not items:
        raise ProvenanceError("No provenance values were supplied for comparison.")
    labels = labels or [f"artifact {index + 1}" for index in range(len(items))]
    first = dict(items[0])
    for label, item in zip(labels[1:], items[1:]):
        if dict(item) != first:
            raise ProvenanceError(f"Provenance mismatch for {label}.")
    return first


def artifact_provenance(artifact: Mapping[str, Any], label: str) -> dict[str, Any]:
    value = artifact.get("provenance")
    if not isinstance(value, dict):
        raise ProvenanceError(f"{label} is missing provenance.")
    return value


def derive_data_mode(provenance: Mapping[str, Any]) -> str:
    classes = set(provenance.get("source_classes", {}).values())
    if classes == {"synthetic"}:
        return "synthetic"
    if "synthetic" not in classes:
        return "real"
    return "mixed"
