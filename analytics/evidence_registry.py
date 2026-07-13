"""Versioned, offline evidence-registry validation for DengueOps."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from formula_registry import formula_evidence_references, known_formula_ids, load_formula_registry

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "config" / "evidence_registry.json"
SCHEMA_PATH = ROOT / "config" / "evidence_registry.schema.json"
PLACEHOLDERS = {"tbd", "todo", "unknown", "placeholder", "dummy", "n/a", "na"}


class EvidenceRegistryError(ValueError):
    """Raised when evidence structure, content, or linkage is invalid."""


def evidence_registry_sha256(path: str | Path = REGISTRY_PATH) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _schema_errors(value: Any, schema_path: str | Path = SCHEMA_PATH) -> list[str]:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [error.message for error in sorted(validator.iter_errors(value), key=lambda e: list(e.path))]


def _is_placeholder(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip() or value.strip().lower() in PLACEHOLDERS


def _resolve_local_document(location: str) -> Path | None:
    if location.startswith(("http://", "https://", "doi:")):
        return None
    candidate = (ROOT / location).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise EvidenceRegistryError("Verified document_location escapes the repository.") from exc
    return candidate


def validate_evidence_registry(
    registry: dict[str, Any],
    *,
    formula_registry: dict[str, Any] | None = None,
    schema_path: str | Path = SCHEMA_PATH,
) -> None:
    errors = _schema_errors(registry, schema_path)
    records = registry.get("evidence", []) if isinstance(registry, dict) else []
    ids = [record.get("evidence_id") for record in records if isinstance(record, dict)]
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        errors.append(f"Duplicate evidence_id values: {duplicates}.")
    known = known_formula_ids(formula_registry or load_formula_registry())
    by_id = {record.get("evidence_id"): record for record in records if isinstance(record, dict)}
    current_year = date.today().year
    for record in records:
        if not isinstance(record, dict):
            continue
        evidence_id = str(record.get("evidence_id", "<missing>"))
        year = record.get("publication_year")
        if isinstance(year, int) and not 1900 <= year <= current_year:
            errors.append(f"{evidence_id} publication_year must be within 1900..{current_year}.")
        unknown = sorted(set(record.get("formula_ids_supported", [])) - known)
        if unknown:
            errors.append(f"{evidence_id} references unknown formula IDs: {unknown}.")
        parent = record.get("supersedes_evidence_id")
        if parent is not None and parent not in by_id:
            errors.append(f"{evidence_id} supersedes unknown evidence ID {parent}.")
        if parent == evidence_id:
            errors.append(f"{evidence_id} cannot supersede itself.")
        if record.get("record_status") == "superseded" and record.get("verification_status") != "superseded":
            errors.append(f"{evidence_id} superseded record status must match verification_status.")
        if record.get("verification_status") == "verified":
            required = ("title", "issuing_organization_or_journal", "findings_summary", "reviewed_by", "review_date", "document_location", "citation_identifier")
            for field in required:
                if _is_placeholder(record.get(field)):
                    errors.append(f"{evidence_id} verified evidence requires non-placeholder {field}.")
            location = record.get("document_location")
            if isinstance(location, str) and location.strip():
                try:
                    local_path = _resolve_local_document(location)
                    if local_path is not None:
                        if not local_path.is_file():
                            errors.append(f"{evidence_id} verified local document does not exist: {location}.")
                        elif record.get("content_sha256") != hashlib.sha256(local_path.read_bytes()).hexdigest():
                            errors.append(f"{evidence_id} content_sha256 does not match its local document.")
                except EvidenceRegistryError as exc:
                    errors.append(str(exc))
            if not record.get("content_sha256"):
                errors.append(f"{evidence_id} verified evidence requires content_sha256.")

    for start in by_id:
        visited: set[str] = set()
        current = start
        while current in by_id and by_id[current].get("supersedes_evidence_id") is not None:
            if current in visited:
                errors.append(f"Supersession cycle detected from {start}.")
                break
            visited.add(current)
            current = by_id[current]["supersedes_evidence_id"]
    if errors:
        raise EvidenceRegistryError(" ".join(dict.fromkeys(errors)))


def load_evidence_registry(path: str | Path = REGISTRY_PATH) -> dict[str, Any]:
    path = Path(path)
    try:
        registry = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvidenceRegistryError(f"Evidence registry is unreadable: {exc}") from exc
    validate_evidence_registry(registry)
    return registry


def get_evidence(evidence_id: str, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = registry or load_evidence_registry()
    for record in registry["evidence"]:
        if record["evidence_id"] == evidence_id:
            return record
    raise EvidenceRegistryError(f"Unknown evidence_id: {evidence_id}.")


def validate_formula_evidence_links(
    evidence_registry: dict[str, Any] | None = None,
    formula_registry: dict[str, Any] | None = None,
) -> None:
    evidence_registry = evidence_registry or load_evidence_registry()
    formula_registry = formula_registry or load_formula_registry()
    validate_evidence_registry(evidence_registry, formula_registry=formula_registry)
    evidence_by_id = {record["evidence_id"]: record for record in evidence_registry["evidence"]}
    links = formula_evidence_references(formula_registry)
    errors: list[str] = []
    for formula_id, evidence_ids in links.items():
        for evidence_id in evidence_ids:
            if evidence_id not in evidence_by_id:
                errors.append(f"{formula_id} references unknown evidence ID {evidence_id}.")
            elif formula_id not in evidence_by_id[evidence_id]["formula_ids_supported"]:
                errors.append(f"{formula_id} and {evidence_id} are not linked bidirectionally.")
    for evidence_id, record in evidence_by_id.items():
        for formula_id in record["formula_ids_supported"]:
            if evidence_id not in links.get(formula_id, ()):
                errors.append(f"{evidence_id} and {formula_id} are not linked bidirectionally.")
    if errors:
        raise EvidenceRegistryError(" ".join(errors))
