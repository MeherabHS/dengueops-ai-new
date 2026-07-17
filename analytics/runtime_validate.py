"""P1.4B uploaded CSV normalization and authoritative validation entry point."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import jsonschema
import pandas as pd

from feature_engineering import FEATURE_COLUMNS, build_features, build_inference_features
from runtime_context import ROOT, RuntimeContextError, require_absolute_directory, require_within
from runtime_policy import (
    EXPECTED_CASE_COLUMNS,
    EXPECTED_CLIMATE_COLUMNS,
    evaluate_quick_forecast_policy,
    load_and_validate_quick_forecast_policy,
)
from runtime_assessment_policy import (
    evaluate_assessment_policy,
    load_and_validate_assessment_policy,
)


CASE_COLUMNS = EXPECTED_CASE_COLUMNS
CLIMATE_COLUMNS = EXPECTED_CLIMATE_COLUMNS
CONTRACT_VERSION = "p1.4b-canonical-upload-v1"
VALIDATION_VERSION = "p1.4b-v1"
NORMALIZATION_POLICY_ID = "UPLOAD.CSV.CANONICAL_EXACT_HEADERS"
NORMALIZATION_POLICY_VERSION = "1.0"
TARGET = "target_cases_next_2w"
HORIZON_WEEKS = 2
FEATURE_BURN_IN_WEEKS = 5
INITIAL_TRAINING_WINDOW = 104
SUPPORTED_ALIASES: dict[str, str] = {}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def issue(code: str, category: str, message: str, *, field: str | None = None,
          severity: str = "error") -> dict[str, Any]:
    value: dict[str, Any] = {"code": code, "category": category, "severity": severity, "message": message}
    if field:
        value["field"] = field
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_and_normalize(source: Path, output: Path, required: list[str], domain: str,
                        issues: list[dict[str, Any]]) -> tuple[pd.DataFrame, str]:
    raw = source.read_bytes()
    if not raw:
        issues.append(issue(f"{domain}_empty", "file", f"The {domain} CSV is empty."))
        return pd.DataFrame(), ""
    if b"\x00" in raw:
        issues.append(issue(f"{domain}_nul_byte", "file", f"The {domain} CSV contains NUL bytes."))
        return pd.DataFrame(), ""
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        issues.append(issue(f"{domain}_invalid_utf8", "file", f"The {domain} CSV must use UTF-8 encoding."))
        return pd.DataFrame(), ""
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    except csv.Error:
        issues.append(issue(f"{domain}_malformed_csv", "file", f"The {domain} CSV is malformed."))
        return pd.DataFrame(), ""
    if not rows or not rows[0]:
        issues.append(issue(f"{domain}_missing_header", "file", f"The {domain} CSV has no header."))
        return pd.DataFrame(), ""
    headers = [value.strip() for value in rows[0]]
    lowered = [value.lower() for value in headers]
    if any(not value for value in headers):
        issues.append(issue(f"{domain}_empty_header", "file", f"The {domain} CSV contains an empty header."))
    if len(set(lowered)) != len(lowered):
        issues.append(issue(f"{domain}_duplicate_header", "file", f"The {domain} CSV contains duplicate headers."))
    if any(len(row) != len(headers) for row in rows[1:]):
        issues.append(issue(f"{domain}_inconsistent_width", "file", f"The {domain} CSV has inconsistent row widths."))
    mapped = [SUPPORTED_ALIASES.get(value, value) for value in headers]
    if mapped != headers:
        headers = mapped
    missing = [column for column in required if column not in headers]
    for column in missing:
        issues.append(issue(f"{domain}_missing_required_column", "schema",
                            f"The {domain} CSV is missing required column '{column}'.", field=column))
    if any(value["severity"] == "error" and value["category"] == "file" for value in issues):
        return pd.DataFrame(), ""
    ordered = [column for column in required if column in headers] + sorted(column for column in headers if column not in required)
    index = {column: headers.index(column) for column in headers}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(ordered)
        for row in rows[1:]:
            writer.writerow([row[index[column]] for column in ordered])
    frame = pd.read_csv(output, dtype=str, keep_default_na=False)
    return frame, sha256_file(output)


def _numeric(frame: pd.DataFrame, column: str, domain: str, issues: list[dict[str, Any]],
             *, integer: bool = False, minimum: float | None = None,
             maximum: float | None = None, allow_blank: bool = False) -> pd.Series | None:
    if column not in frame:
        return None
    raw = frame[column].replace("", pd.NA)
    values = pd.to_numeric(raw, errors="coerce")
    invalid = values.isna() & ~(allow_blank & raw.isna())
    if invalid.any() or (~values.dropna().map(math.isfinite)).any():
        issues.append(issue(f"{domain}_invalid_{column}", "schema", f"{column} must contain finite numeric values.", field=column))
        return None
    if integer and (values.dropna() != values.dropna().round()).any():
        issues.append(issue(f"{domain}_noninteger_{column}", "schema", f"{column} must contain integer values.", field=column))
    if minimum is not None and (values.dropna() < minimum).any():
        issues.append(issue(f"{domain}_{column}_below_minimum", "schema", f"{column} must be at least {minimum:g}.", field=column))
    if maximum is not None and (values.dropna() > maximum).any():
        issues.append(issue(f"{domain}_{column}_above_maximum", "schema", f"{column} must be at most {maximum:g}.", field=column))
    return values


def _validate_periods(frame: pd.DataFrame, domain: str, issues: list[dict[str, Any]]) -> list[tuple[int, int]]:
    years = _numeric(frame, "epi_year", domain, issues, integer=True, minimum=1900, maximum=2100)
    weeks = _numeric(frame, "epi_week", domain, issues, integer=True, minimum=1, maximum=52)
    if years is None or weeks is None or "date_start" not in frame:
        return []
    parsed = pd.to_datetime(frame["date_start"], format="%Y-%m-%d", errors="coerce")
    if parsed.isna().any():
        issues.append(issue(f"{domain}_invalid_date", "temporal", "date_start must use YYYY-MM-DD.", field="date_start"))
        return []
    periods = [(int(year), int(week)) for year, week in zip(years, weeks)]
    if len(set(periods)) != len(periods):
        issues.append(issue(f"{domain}_duplicate_period", "temporal", f"The {domain} CSV contains duplicate epidemiological periods."))
    if periods != sorted(periods):
        issues.append(issue(f"{domain}_not_chronological", "temporal", f"The {domain} CSV must be in chronological order."))
    ordinals = [year * 52 + week for year, week in periods]
    if any(ordinals[index] - ordinals[index - 1] != 1 for index in range(1, len(ordinals))):
        issues.append(issue(f"{domain}_missing_period", "temporal", f"The {domain} CSV contains missing or non-contiguous weeks."))
    mismatch = False
    for year, week, actual in zip(years, weeks, parsed):
        try:
            expected = date.fromisocalendar(int(year), int(week), 1)
        except ValueError:
            mismatch = True
            break
        if actual.date() != expected:
            mismatch = True
            break
    if mismatch:
        issues.append(issue(f"{domain}_date_period_mismatch", "temporal",
                            "date_start must be the ISO Monday matching epi_year and epi_week.", field="date_start"))
    return periods


def _geography(frame: pd.DataFrame, domain: str, issues: list[dict[str, Any]]) -> dict[str, str] | None:
    required = ("geography_level", "geography_id", "geography_name")
    if any(column not in frame for column in required):
        return None
    result: dict[str, str] = {}
    for column in required:
        values = [value.strip() for value in frame[column].astype(str).tolist()]
        unique = sorted(set(values))
        if len(unique) != 1 or not unique[0]:
            issues.append(issue(f"{domain}_inconsistent_{column}", "schema",
                                f"{column} must identify one non-empty geography.", field=column))
            return None
        result[column] = unique[0]
    return result


def _validate_case(frame: pd.DataFrame, issues: list[dict[str, Any]]) -> tuple[list[tuple[int, int]], dict[str, str] | None]:
    periods = _validate_periods(frame, "case", issues)
    geography = _geography(frame, "case", issues)
    cases = _numeric(frame, "cases", "case", issues, integer=True, minimum=0)
    deaths = _numeric(frame, "deaths", "case", issues, integer=True, minimum=0, allow_blank=True)
    if cases is not None and deaths is not None and ((deaths.notna()) & (deaths > cases)).any():
        issues.append(issue("case_deaths_exceed_cases", "schema", "Known deaths cannot exceed cases.", field="deaths"))
    for column in ("deaths_data_status", "source_type"):
        if column in frame and frame[column].astype(str).str.strip().eq("").any():
            issues.append(issue(f"case_blank_{column}", "schema", f"{column} must be non-empty.", field=column))
    return periods, geography


def _validate_climate(frame: pd.DataFrame, issues: list[dict[str, Any]]) -> tuple[list[tuple[int, int]], dict[str, str] | None]:
    periods = _validate_periods(frame, "climate", issues)
    geography = _geography(frame, "climate", issues)
    _numeric(frame, "rainfall_mm", "climate", issues, minimum=0)
    _numeric(frame, "avg_temp_c", "climate", issues, minimum=-60, maximum=60)
    _numeric(frame, "humidity_pct", "climate", issues, minimum=0, maximum=100)
    coverage = _numeric(frame, "coverage_days", "climate", issues, integer=True)
    if coverage is not None and not coverage.dropna().eq(7).all():
        issues.append(issue("climate_invalid_coverage_days", "schema", "coverage_days must equal 7.", field="coverage_days"))
    if "aggregation_method" in frame and frame["aggregation_method"].astype(str).str.strip().eq("").any():
        issues.append(issue("climate_blank_aggregation_method", "schema", "aggregation_method must be non-empty.", field="aggregation_method"))
    if geography and geography["geography_level"] == "point":
        _numeric(frame, "latitude", "climate", issues, minimum=-90, maximum=90)
        _numeric(frame, "longitude", "climate", issues, minimum=-180, maximum=180)
    return periods, geography


def compute_dataset_id(dengue_bytes: bytes, climate_bytes: bytes, deployment_id: str,
                       feature_order_sha256: str) -> str:
    digest = hashlib.sha256()
    for label, value in ((b"dengue\0", dengue_bytes), (b"climate\0", climate_bytes)):
        digest.update(label)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    digest.update(b"deployment\0" + deployment_id.encode("utf-8"))
    digest.update(b"contract\0" + CONTRACT_VERSION.encode("utf-8"))
    digest.update(b"features\0" + feature_order_sha256.encode("ascii"))
    return digest.hexdigest()


def _operational_bundle_identity() -> str | None:
    paths = [ROOT / "data" / name for name in ("zones.json", "facilities.json", "inventory.json")]
    if not all(path.exists() for path in paths):
        return None
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8") + b"\0" + path.read_bytes())
    return digest.hexdigest()


def _single_metadata_value(frame: pd.DataFrame, column: str) -> str | None:
    if column not in frame:
        return None
    values = sorted({str(value).strip() for value in frame[column].tolist() if str(value).strip()})
    return values[0] if len(values) == 1 else None


def _contains_approximated_values(frame: pd.DataFrame) -> bool | None:
    if "is_approximated" not in frame:
        return None
    values = {str(value).strip().lower() for value in frame["is_approximated"].tolist()}
    if not values or not values.issubset({"true", "false"}):
        return None
    return "true" in values


def validate(args: argparse.Namespace) -> dict[str, Any]:
    runtime_root=getattr(args,"runtime_root",None)
    if runtime_root:
        from runtime_active_model import resolve_active_model
        resolve_active_model(ROOT,require_absolute_directory(runtime_root,"runtime root"),args.deployment_id)
    workspace = Path(args.workspace_root).resolve()
    dengue_input = require_within(workspace, args.dengue_input, "dengue input")
    climate_input = require_within(workspace, args.climate_input, "climate input")
    dengue_output = require_within(workspace, args.canonical_dengue_output, "canonical dengue output")
    climate_output = require_within(workspace, args.canonical_climate_output, "canonical climate output")
    validation_output = require_within(workspace, args.validation_output, "validation output")
    profile_path = ROOT / "config" / "deployments" / args.deployment_id / "profile.json"
    if not profile_path.exists():
        raise RuntimeContextError("The requested deployment profile is unavailable.")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    quick_policy, quick_policy_sha256 = load_and_validate_quick_forecast_policy(args.deployment_id)
    assessment_policy, assessment_policy_sha256 = load_and_validate_assessment_policy(args.deployment_id)
    feature_hash = str(profile.get("forecast_uncertainty", {}).get("feature_order_sha256", ""))
    if len(feature_hash) != 64:
        raise RuntimeContextError("The deployment feature-order identity is unavailable.")
    issues: list[dict[str, Any]] = []
    case_frame, canonical_case_hash = _load_and_normalize(dengue_input, dengue_output, CASE_COLUMNS, "case", issues)
    climate_frame, canonical_climate_hash = _load_and_normalize(climate_input, climate_output, CLIMATE_COLUMNS, "climate", issues)
    case_periods, case_geography = _validate_case(case_frame, issues)
    climate_periods, climate_geography = _validate_climate(climate_frame, issues)
    overlap = sorted(set(case_periods) & set(climate_periods))
    if not overlap:
        issues.append(issue("no_case_climate_overlap", "alignment", "Case and climate data have no overlapping epidemiological period."))
    else:
        ordinals = [year * 52 + week for year, week in overlap]
        if any(ordinals[index] - ordinals[index - 1] != 1 for index in range(1, len(ordinals))):
            issues.append(issue("noncontiguous_overlap", "alignment", "The accepted case/climate overlap is not contiguous."))
    if case_geography and climate_geography and case_geography["geography_id"] != climate_geography["geography_id"]:
        issues.append(issue("geography_mismatch", "alignment", "Case and climate geography identities do not match."))
    labelled_rows = max(0, len(overlap) - FEATURE_BURN_IN_WEEKS - HORIZON_WEEKS)
    constructible_feature_count = 0
    valid_inference_row = False
    if not any(value["severity"] == "error" for value in issues):
        try:
            training_features, _ = build_features(dengue_output, climate_output, output_path=None)
            inference_features = build_inference_features(dengue_output, climate_output)
            labelled_rows = len(training_features)
            constructible_feature_count = len(FEATURE_COLUMNS) if list(training_features.loc[:, FEATURE_COLUMNS].columns) == list(FEATURE_COLUMNS) else 0
            if not inference_features.empty:
                latest = inference_features.iloc[-1]
                valid_inference_row = (
                    list(latest.loc[FEATURE_COLUMNS].index) == list(FEATURE_COLUMNS)
                    and pd.to_numeric(latest.loc[FEATURE_COLUMNS], errors="coerce").notna().all()
                    and bool(overlap)
                    and (int(latest["epi_year"]), int(latest["epi_week"])) == overlap[-1]
                )
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(issue("feature_contract_unavailable", "eligibility",
                                "The governed feature and inference contract could not be constructed."))
    if len(overlap) < INITIAL_TRAINING_WINDOW:
        issues.append(issue("insufficient_accepted_history", "eligibility",
                            f"At least {INITIAL_TRAINING_WINDOW} accepted overlapping weeks are required."))
    error_count = sum(value["severity"] == "error" for value in issues)
    registry_path = ROOT / "config" / "candidate_models.json"
    registry_bytes = registry_path.read_bytes()
    registry = json.loads(registry_bytes.decode("utf-8"))
    source_metadata = {
        "cases": {
            "source_type": _single_metadata_value(case_frame, "source_type"),
            "aggregation_method": "weekly_epi_week_case_count",
            "contains_approximated_values": _contains_approximated_values(case_frame),
        },
        "climate": {
            "source_type": _single_metadata_value(climate_frame, "source_type"),
            "aggregation_method": _single_metadata_value(climate_frame, "aggregation_method"),
            "contains_approximated_values": _contains_approximated_values(climate_frame),
        },
    }
    temporal_context = {
        "chronological_order_valid": not any(value["code"] in {"case_not_chronological", "climate_not_chronological"} for value in issues),
        "duplicate_periods_absent": not any(value["code"] in {"case_duplicate_period", "climate_duplicate_period"} for value in issues),
        "contiguous_history": not any(value["code"] in {"case_missing_period", "climate_missing_period", "noncontiguous_overlap"} for value in issues),
        "case_climate_aligned": bool(case_periods) and case_periods == climate_periods,
    }
    quick = evaluate_quick_forecast_policy(quick_policy, {
        "validation_passed": error_count == 0,
        "deployment_id": args.deployment_id,
        "deployment_gate": profile.get("deployment_gate"),
        "case_geography": case_geography,
        "climate_geography": climate_geography,
        "canonical_contract_version": CONTRACT_VERSION,
        "feature_order_sha256": feature_hash,
        "constructible_feature_count": constructible_feature_count,
        "target": TARGET,
        "horizon_weeks": HORIZON_WEEKS,
        "approved_model_id": profile.get("model", {}).get("model_id"),
        "approved_model_family": profile.get("model", {}).get("model_family"),
        "approved_model_parameters_sha256": profile.get("model", {}).get("model_parameters_sha256"),
        "candidate_registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        "source_metadata": source_metadata,
        "overlap_weeks": len(overlap),
        "labelled_rows": labelled_rows,
        **temporal_context,
        "valid_inference_row": valid_inference_row,
    })
    if quick.get("policySha256") != quick_policy_sha256:
        raise RuntimeContextError("Quick Forecast policy identity changed during evaluation.")
    assess = evaluate_assessment_policy(assessment_policy, {
        "validation_passed": error_count == 0,
        "deployment_id": args.deployment_id,
        "case_geography": case_geography,
        "climate_geography": climate_geography,
        "canonical_contract_version": CONTRACT_VERSION,
        "feature_order_sha256": feature_hash,
        "constructible_feature_count": constructible_feature_count,
        "target": TARGET,
        "horizon_weeks": HORIZON_WEEKS,
        "source_metadata": source_metadata,
        "labelled_rows": labelled_rows,
        "available_history_weeks": len(overlap),
        "candidate_registry": registry,
        "candidate_registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
        **temporal_context,
    })
    if assess.get("policySha256") != assessment_policy_sha256:
        raise RuntimeContextError("Dataset-assessment policy identity changed during evaluation.")
    if not canonical_case_hash or not canonical_climate_hash:
        raise RuntimeContextError("Canonical uploaded datasets could not be serialized.")
    dataset_id = compute_dataset_id(dengue_output.read_bytes(), climate_output.read_bytes(), args.deployment_id, feature_hash)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = "invalid" if error_count else "ready"
    result: dict[str, Any] = {
        "schemaVersion": "1.0",
        "workspaceId": args.workspace_id,
        "datasetId": dataset_id,
        "deploymentId": args.deployment_id,
        "workflowMode": args.workflow_mode,
        "status": status,
        "createdAt": args.created_at,
        "updatedAt": now,
        "files": {
            "original": {
                "dengueSha256": sha256_file(dengue_input),
                "climateSha256": sha256_file(climate_input),
            },
            "canonical": {
                "dengueSha256": canonical_case_hash,
                "climateSha256": canonical_climate_hash,
            },
        },
        "normalization": {
            "policyId": NORMALIZATION_POLICY_ID,
            "policyVersion": NORMALIZATION_POLICY_VERSION,
            "canonicalContractVersion": CONTRACT_VERSION,
            "supportedAliases": SUPPORTED_ALIASES,
            "behavior": ["UTF-8 BOM removal", "trimmed header names", "canonical required-column order", "LF newline serialization"],
        },
        "datasetIdentity": {
            "featureOrderSha256": feature_hash,
            "target": TARGET,
            "horizonWeeks": HORIZON_WEEKS,
            "validationContractVersion": VALIDATION_VERSION,
            "geography": case_geography,
            "operationalInputBundleSha256": _operational_bundle_identity(),
        },
        "counts": {
            "caseRows": len(case_frame),
            "climateRows": len(climate_frame),
            "overlapWeeks": len(overlap),
            "labelledRows": labelled_rows,
        },
        "issues": issues,
        "eligibility": {
            "quickForecast": quick,
            "assessDataset": assess,
        },
    }
    if overlap:
        result["acceptedPeriod"] = {
            "start": f"{overlap[0][0]}-W{overlap[0][1]:02d}",
            "end": f"{overlap[-1][0]}-W{overlap[-1][1]:02d}",
        }
    schema = json.loads((ROOT / "config" / "runtime_workspace.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(result)
    _atomic_json(validation_output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate uploaded DengueOps CSVs inside an isolated workspace.")
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--runtime-root")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--dengue-input", required=True)
    parser.add_argument("--climate-input", required=True)
    parser.add_argument("--canonical-dengue-output", required=True)
    parser.add_argument("--canonical-climate-output", required=True)
    parser.add_argument("--validation-output", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--workflow-mode", choices=("quick_forecast", "assess_dataset"), required=True)
    args = parser.parse_args()
    try:
        result = validate(args)
        print(json.dumps({"status": result["status"], "workspaceId": result["workspaceId"], "datasetId": result["datasetId"]}))
        return 0
    except Exception as exc:
        try:
            output = require_within(args.workspace_root, args.validation_output, "validation output")
            _atomic_json(output, {
                "schemaVersion": "1.0",
                "systemFailure": True,
                "code": "runtime_validation_system_failure",
                "message": "Authoritative validation could not be completed.",
            })
        except Exception:
            pass
        print(f"runtime_validation_system_failure: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
