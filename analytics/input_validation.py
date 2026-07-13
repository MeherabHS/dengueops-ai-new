"""Canonical input validation and manifest generation for DengueOps AI."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from input_sources import InputSourcePlan, get_descriptor_by_tag, get_source_descriptor

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CASES_PATH = DATA_DIR / "dengue_cases.csv"
CLIMATE_PATH = DATA_DIR / "climate_data.csv"
ZONES_PATH = DATA_DIR / "zones.json"
FACILITIES_PATH = DATA_DIR / "facilities.json"
INVENTORY_PATH = DATA_DIR / "inventory.json"
MANIFEST_PATH = DATA_DIR / "input_manifest.json"
OPENDENGUE_METADATA_PATH = DATA_DIR / "raw" / "opendengue_bangladesh_metadata.json"
NASA_METADATA_PATH = DATA_DIR / "raw" / "nasa_power_dhaka_south_metadata.json"
BENCHMARK_METADATA_PATH = DATA_DIR / "raw" / "synthetic_benchmark_metadata.json"

MIN_OVERLAP_WEEKS = 104
FEATURE_BURN_IN_WEEKS = 5
TARGET_HORIZON_WEEKS = 2
MIN_EXPECTED_SUPERVISED_ROWS = 97

CASE_REQUIRED_COLUMNS = {
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "city", "cases", "deaths", "deaths_data_status",
    "source_type", "is_approximated", "approximation_method",
}
CLIMATE_REQUIRED_COLUMNS = {
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "latitude", "longitude", "rainfall_mm", "avg_temp_c",
    "humidity_pct", "coverage_days", "source_type", "aggregation_method",
    "is_approximated",
}


class InputValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class DatasetValidation:
    domain: str
    status: str = "failed"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_hashes: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    start_period: tuple[int, int] | None = None
    end_period: tuple[int, int] | None = None
    geography_level: str | None = None
    geography_id: str | None = None
    geography_name: str | None = None
    source_tag: str | None = None
    source_id: str | None = None
    source_class: str | None = None
    units: dict[str, str] = field(default_factory=dict)
    paths: list[Path] = field(default_factory=list)
    week_keys: tuple[tuple[int, int], ...] = field(default_factory=tuple, repr=False)
    associated_geography_id: str | None = field(default=None, repr=False)
    adapter_metadata: dict[str, Any] = field(default_factory=dict)

    def finalize(self) -> "DatasetValidation":
        self.status = "passed" if not self.errors else "failed"
        return self


@dataclass
class CrossSourceValidation:
    status: str = "failed"
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)
    overlap_weeks: int = 0
    expected_supervised_rows: int = 0
    start_period: tuple[int, int] | None = None
    end_period: tuple[int, int] | None = None

    def finalize(self) -> "CrossSourceValidation":
        self.status = "passed" if not self.errors else "failed"
        return self


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _is_blank(value: Any) -> bool:
    return pd.isna(value) or not str(value).strip()


def _parse_boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not pd.isna(value) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return None


def _integer_series(df: pd.DataFrame, column: str, errors: list[str]) -> pd.Series | None:
    values = pd.to_numeric(df[column], errors="coerce")
    valid = values.notna() & values.map(math.isfinite) & (values == values.round())
    if not valid.all():
        errors.append(f"{column} must contain only non-null integers.")
        return None
    return values.astype(int)


def _finite_numeric_series(df: pd.DataFrame, column: str, errors: list[str]) -> pd.Series | None:
    values = pd.to_numeric(df[column], errors="coerce")
    if values.isna().any() or not values.map(math.isfinite).all():
        errors.append(f"{column} must contain only finite non-null numbers.")
        return None
    return values.astype(float)


def _validate_time_and_geography(
    df: pd.DataFrame, result: DatasetValidation
) -> tuple[pd.Series | None, pd.Series | None]:
    years = _integer_series(df, "epi_year", result.errors)
    weeks = _integer_series(df, "epi_week", result.errors)
    if years is not None and not years.between(1900, 2100).all():
        result.errors.append("epi_year must be between 1900 and 2100.")
    if weeks is not None and not weeks.between(1, 52).all():
        invalid = sorted(set(weeks[~weeks.between(1, 52)].tolist()))
        result.errors.append(f"epi_week must be between 1 and 52; invalid values: {invalid}.")

    parsed_dates = pd.to_datetime(df["date_start"], format="%Y-%m-%d", errors="coerce")
    if parsed_dates.isna().any():
        result.errors.append("date_start must contain valid ISO dates (YYYY-MM-DD).")
    elif years is not None and weeks is not None and weeks.between(1, 52).all():
        mismatches: list[str] = []
        for idx, (year, week, actual) in enumerate(zip(years, weeks, parsed_dates)):
            expected = date.fromisocalendar(int(year), int(week), 1)
            if actual.date() != expected:
                mismatches.append(f"row {idx}: {actual.date()} != {expected} for {year}-W{week}")
        if mismatches:
            result.errors.append("date_start/week mismatch: " + "; ".join(mismatches[:5]))

    for column in ("geography_level", "geography_id", "geography_name"):
        if df[column].map(_is_blank).any():
            result.errors.append(f"{column} must be nonempty.")
    geo_ids = df["geography_id"].dropna().astype(str).str.strip().unique()
    geo_levels = df["geography_level"].dropna().astype(str).str.strip().unique()
    geo_names = df["geography_name"].dropna().astype(str).str.strip().unique()
    if len(geo_ids) != 1 or len(geo_levels) != 1 or len(geo_names) != 1:
        result.errors.append("Input must contain exactly one consistent geography series.")
    else:
        result.geography_id = geo_ids[0]
        result.geography_level = geo_levels[0].lower()
        result.geography_name = geo_names[0]

    if years is not None and weeks is not None:
        keys = list(zip(years.astype(int), weeks.astype(int)))
        geo_keys = list(zip(years.astype(int), weeks.astype(int), df["geography_id"].astype(str)))
        if len(set(geo_keys)) != len(geo_keys):
            result.errors.append("Duplicate (epi_year, epi_week, geography_id) keys found.")
        if keys != sorted(keys):
            result.errors.append("Rows must be chronologically ordered by epi_year and epi_week.")
        if len(set(keys)) == len(keys) and keys == sorted(keys):
            ordinals = [year * 52 + week for year, week in keys]
            gaps = [(keys[i - 1], keys[i]) for i in range(1, len(keys)) if ordinals[i] - ordinals[i - 1] != 1]
            if gaps:
                result.errors.append("Missing or non-contiguous interior epidemiological weeks: " + ", ".join(f"{a}->{b}" for a, b in gaps[:5]))
            result.week_keys = tuple(keys)
            if keys:
                result.start_period, result.end_period = keys[0], keys[-1]
    return years, weeks


def _set_source(
    df: pd.DataFrame, result: DatasetValidation, expected_source: str | None
) -> None:
    values = df["source_type"].dropna().astype(str).str.strip().unique()
    if len(values) != 1 or not values[0]:
        result.errors.append("source_type must contain exactly one nonempty value.")
        return
    result.source_tag = values[0]
    expected = get_source_descriptor(expected_source) if expected_source else None
    detected = get_descriptor_by_tag(result.source_tag)
    if expected and result.source_tag != expected.canonical_tag:
        result.errors.append(f"source_type '{result.source_tag}' does not match selected source '{expected.canonical_tag}'.")
    descriptor = expected or detected
    if descriptor is None:
        result.errors.append(f"source_type '{result.source_tag}' is not a recognized canonical source tag.")
        result.source_id = result.source_tag
        result.source_class = "unknown"
    else:
        result.source_id = descriptor.source_id
        result.source_class = descriptor.source_class


def _load_adapter_metadata(result: DatasetValidation, source_id: str | None, canonical_output: Path) -> None:
    if source_id == "synthetic_benchmark":
        _load_benchmark_metadata(result, canonical_output)
        return
    metadata_paths = {"opendengue": OPENDENGUE_METADATA_PATH, "nasa_power": NASA_METADATA_PATH}
    if source_id not in metadata_paths:
        return
    path = metadata_paths[source_id]
    if not path.exists():
        result.errors.append(f"Required {source_id} adapter metadata is missing: {path}")
        return
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result.errors.append(f"{source_id} adapter metadata is unreadable: {exc}")
        return
    if not isinstance(metadata, dict):
        result.errors.append(f"{source_id} adapter metadata must be a JSON object.")
        return
    if metadata.get("metadata_schema_version") != "1.0":
        result.errors.append(f"{source_id} adapter metadata schema is unsupported.")
    if metadata.get("adapter") != source_id:
        result.errors.append(f"{source_id} adapter metadata identity does not match.")
    output_value = metadata.get("output_path")
    output_hash = metadata.get("output_sha256") or metadata.get("weekly_output_sha256")
    if not output_value or not output_hash:
        result.errors.append(f"{source_id} adapter metadata lacks output path/hash.")
    else:
        output_path = Path(output_value)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        if output_path.resolve() != canonical_output.resolve():
            result.errors.append(f"{source_id} metadata references a different canonical output.")
        elif _sha256(canonical_output) != output_hash:
            result.errors.append(f"{source_id} sidecar/output hash mismatch.")
    raw_path_key = "raw_file_path" if source_id == "opendengue" else "cache_file_path"
    raw_hash_key = "raw_file_sha256" if source_id == "opendengue" else "cache_file_sha256"
    raw_value, raw_hash = metadata.get(raw_path_key), metadata.get(raw_hash_key)
    if not raw_value or not raw_hash:
        result.errors.append(f"{source_id} adapter metadata lacks raw/cache path/hash.")
    else:
        raw_path = Path(raw_value)
        if not raw_path.is_absolute():
            raw_path = ROOT / raw_path
        if not raw_path.exists() or _sha256(raw_path) != raw_hash:
            result.errors.append(f"{source_id} sidecar/raw cache hash mismatch.")
    if not result.errors:
        result.adapter_metadata = metadata


def _load_benchmark_metadata(result: DatasetValidation, canonical_output: Path) -> None:
    path = BENCHMARK_METADATA_PATH
    if not path.exists():
        result.errors.append(f"Required synthetic_benchmark adapter metadata is missing: {path}")
        return
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        result.errors.append(f"synthetic_benchmark adapter metadata is unreadable: {exc}")
        return
    if not isinstance(metadata, dict):
        result.errors.append("synthetic_benchmark adapter metadata must be a JSON object.")
        return
    for key, expected in (
        ("metadata_schema_version", "1.0"), ("adapter", "synthetic_benchmark"),
        ("simulation_version", "benchmark-v1"), ("config_version", "1.0"),
    ):
        if metadata.get(key) != expected:
            result.errors.append(f"synthetic_benchmark metadata {key} is unsupported or mismatched.")
    if not isinstance(metadata.get("seed"), int) or not metadata.get("scenario"):
        result.errors.append("synthetic_benchmark metadata must contain scenario and integer seed.")
    output_files, output_hashes = metadata.get("output_files"), metadata.get("output_hashes")
    required = ("dengue_cases.csv", "climate_data.csv", "zones.json", "facilities.json", "inventory.json")
    if not isinstance(output_files, dict) or not isinstance(output_hashes, dict):
        result.errors.append("synthetic_benchmark metadata lacks canonical output paths/hashes.")
    else:
        for name in required:
            value, expected_hash = output_files.get(name), output_hashes.get(name)
            if not value or not expected_hash:
                result.errors.append(f"synthetic_benchmark metadata lacks path/hash for {name}.")
                continue
            output_path = Path(value)
            if not output_path.is_absolute():
                output_path = ROOT / output_path
            expected_path = DATA_DIR / name
            if output_path.resolve() != expected_path.resolve():
                result.errors.append(f"synthetic_benchmark metadata references a different {name} output.")
            elif not output_path.exists() or _sha256(output_path) != expected_hash:
                result.errors.append(f"synthetic_benchmark sidecar/output hash mismatch for {name}.")
        if canonical_output.name in required and output_hashes.get(canonical_output.name) != _sha256(canonical_output):
            result.errors.append(f"synthetic_benchmark sidecar/output hash mismatch for {canonical_output.name}.")
    period, geography = metadata.get("period"), metadata.get("geography")
    if not isinstance(period, dict) or not period.get("start") or not period.get("end"):
        result.errors.append("synthetic_benchmark metadata period is missing.")
    elif result.start_period and result.end_period:
        actual = {
            "start": {"epi_year": result.start_period[0], "epi_week": result.start_period[1]},
            "end": {"epi_year": result.end_period[0], "epi_week": result.end_period[1]},
        }
        if period != actual:
            result.errors.append("synthetic_benchmark metadata period does not match canonical data.")
    if not isinstance(geography, dict) or (geography.get("level"), geography.get("id"), geography.get("name")) != ("city", "BGD-DHAKA-SOUTH", "Dhaka South"):
        result.errors.append("synthetic_benchmark metadata geography is unsupported or mismatched.")
    result.adapter_metadata = {
        key: metadata.get(key) for key in (
            "metadata_schema_version", "adapter", "simulation_version", "config_version",
            "scenario", "seed", "configuration_fingerprint", "period", "geography",
            "output_files", "output_hashes", "reporting_delay_rule",
        ) if metadata.get(key) is not None
    }
def validate_case_dataset(path: str | Path, expected_source: str | None) -> DatasetValidation:
    path = Path(path)
    result = DatasetValidation(domain="cases", paths=[path], units={"cases": "count/week", "deaths": "count/week"})
    if not path.exists():
        result.errors.append(f"Case file does not exist: {path}")
        return result.finalize()
    try:
        result.file_hashes[_display_path(path)] = _sha256(path)
        df = pd.read_csv(path)
    except Exception as exc:
        result.errors.append(f"Case file is not readable: {exc}")
        return result.finalize()
    result.counts = {"rows": len(df)}
    if df.empty:
        result.errors.append("Case dataset is empty.")
        return result.finalize()
    missing = CASE_REQUIRED_COLUMNS - set(df.columns)
    if missing:
        result.errors.append(f"Case dataset missing required columns: {sorted(missing)}")
        return result.finalize()

    _validate_time_and_geography(df, result)
    cases = _integer_series(df, "cases", result.errors)
    if cases is not None and (cases < 0).any():
        result.errors.append("cases must be nonnegative.")
    deaths = pd.to_numeric(df["deaths"], errors="coerce")
    invalid = df["deaths"].notna() & (deaths.isna() | ~deaths.fillna(0).map(math.isfinite) | (deaths.fillna(0) != deaths.fillna(0).round()) | (deaths.fillna(0) < 0))
    if invalid.any():
        result.errors.append("deaths must be null or a nonnegative integer.")
    elif cases is not None:
        known = deaths.notna()
        if (deaths[known] > cases[known]).any():
            result.errors.append("Known deaths cannot exceed cases.")
    if df["deaths_data_status"].map(_is_blank).any():
        result.errors.append("deaths_data_status must be nonempty.")
    parsed = df["is_approximated"].map(_parse_boolean)
    if parsed.isna().any():
        result.errors.append("is_approximated must contain parseable boolean values.")
    elif parsed.any() and df.loc[parsed, "approximation_method"].map(_is_blank).any():
        result.errors.append("approximation_method is required when is_approximated is true.")
    _set_source(df, result, expected_source)
    _load_adapter_metadata(result, expected_source, path)
    return result.finalize()


def validate_climate_dataset(path: str | Path, expected_source: str | None) -> DatasetValidation:
    path = Path(path)
    result = DatasetValidation(
        domain="climate",
        paths=[path],
        units={"rainfall_mm": "mm/week", "avg_temp_c": "degrees_celsius", "humidity_pct": "percent"},
    )
    if not path.exists():
        result.errors.append(f"Climate file does not exist: {path}")
        return result.finalize()
    try:
        result.file_hashes[_display_path(path)] = _sha256(path)
        df = pd.read_csv(path)
    except Exception as exc:
        result.errors.append(f"Climate file is not readable: {exc}")
        return result.finalize()
    result.counts = {"rows": len(df)}
    if df.empty:
        result.errors.append("Climate dataset is empty.")
        return result.finalize()
    missing = CLIMATE_REQUIRED_COLUMNS - set(df.columns)
    if missing:
        result.errors.append(f"Climate dataset missing required columns: {sorted(missing)}")
        return result.finalize()

    _validate_time_and_geography(df, result)
    rainfall = _finite_numeric_series(df, "rainfall_mm", result.errors)
    temperature = _finite_numeric_series(df, "avg_temp_c", result.errors)
    humidity = _finite_numeric_series(df, "humidity_pct", result.errors)
    coverage = _integer_series(df, "coverage_days", result.errors)
    if rainfall is not None and (rainfall < 0).any():
        result.errors.append("rainfall_mm must be nonnegative.")
    if temperature is not None and not temperature.between(-60, 60).all():
        result.errors.append("avg_temp_c must be between -60 and 60 degrees Celsius.")
    if humidity is not None and not humidity.between(0, 100).all():
        result.errors.append("humidity_pct must be between 0 and 100.")
    if coverage is not None and not (coverage == 7).all():
        result.errors.append("coverage_days must equal 7 for every modeled week.")
    if df["aggregation_method"].map(_is_blank).any():
        result.errors.append("aggregation_method must be nonempty.")
    parsed = df["is_approximated"].map(_parse_boolean)
    if parsed.isna().any():
        result.errors.append("is_approximated must contain parseable boolean values.")

    if result.geography_level == "point":
        latitude = _finite_numeric_series(df, "latitude", result.errors)
        longitude = _finite_numeric_series(df, "longitude", result.errors)
        if latitude is not None and not latitude.between(-90, 90).all():
            result.errors.append("Point latitude must be between -90 and 90.")
        if longitude is not None and not longitude.between(-180, 180).all():
            result.errors.append("Point longitude must be between -180 and 180.")
        if "associated_geography_id" in df.columns:
            associated = df["associated_geography_id"].dropna().astype(str).str.strip().unique()
            if len(associated) == 1 and associated[0]:
                result.associated_geography_id = associated[0]
    _set_source(df, result, expected_source)
    _load_adapter_metadata(result, expected_source, path)
    return result.finalize()


def _load_json_list(path: Path, label: str, errors: list[str]) -> list[dict]:
    if not path.exists():
        errors.append(f"{label} file does not exist: {path}")
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"{label} file is not readable JSON: {exc}")
        return []
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        errors.append(f"{label} must be a JSON array of objects.")
        return []
    return value


def _number(row: dict, field_name: str, label: str, errors: list[str]) -> float | None:
    value = row.get(field_name)
    if isinstance(value, bool):
        errors.append(f"{label}.{field_name} must be numeric.")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        errors.append(f"{label}.{field_name} must be numeric.")
        return None
    if not math.isfinite(number):
        errors.append(f"{label}.{field_name} must be finite.")
        return None
    return number


def validate_operational_inputs(
    zones_path: str | Path,
    facilities_path: str | Path,
    inventory_path: str | Path,
    expected_source: str | None,
) -> DatasetValidation:
    paths = [Path(zones_path), Path(facilities_path), Path(inventory_path)]
    result = DatasetValidation(
        domain="operational",
        paths=paths,
        units={
            "capacity": "beds", "current_stock": "item_units",
            "baseline_daily_consumption": "item_units/day", "avg_length_of_stay": "days",
        },
    )
    for path in paths:
        if path.exists():
            try:
                result.file_hashes[_display_path(path)] = _sha256(path)
            except OSError as exc:
                result.errors.append(f"Cannot hash {path.name}: {exc}")
    zones = _load_json_list(paths[0], "zones", result.errors)
    facilities = _load_json_list(paths[1], "facilities", result.errors)
    inventory = _load_json_list(paths[2], "inventory", result.errors)
    result.counts = {"zones": len(zones), "facilities": len(facilities), "inventory_records": len(inventory)}
    if result.errors:
        return result.finalize()

    zone_ids: list[str] = []
    population_shares: list[float] = []
    zone_numeric = (
        "population_share", "density_weight", "facility_pressure_weight",
        "mobility_corridor_weight", "vulnerability_weight", "exposure_index",
        "current_anomaly_adjustment",
    )
    normalized = set(zone_numeric) - {"current_anomaly_adjustment"}
    zone_cities: set[str] = set()
    for index, zone in enumerate(zones):
        label = f"zones[{index}]"
        zid = str(zone.get("zone_id", "")).strip()
        if not zid:
            result.errors.append(f"{label}.zone_id must be nonempty.")
        zone_ids.append(zid)
        if _is_blank(zone.get("zone_name")):
            result.errors.append(f"{label}.zone_name must be nonempty.")
        if _is_blank(zone.get("city")):
            result.errors.append(f"{label}.city must be nonempty.")
        else:
            zone_cities.add(str(zone["city"]).strip())
        for field_name in zone_numeric:
            value = _number(zone, field_name, label, result.errors)
            if value is not None and field_name in normalized and not 0 <= value <= 1:
                result.errors.append(f"{label}.{field_name} must be within 0 and 1.")
            if field_name == "population_share" and value is not None:
                population_shares.append(value)
    if len(set(zone_ids)) != len(zone_ids):
        result.errors.append("zone_id values must be unique.")
    if population_shares and abs(sum(population_shares) - 1.0) > 0.001:
        result.errors.append("Zone population_share values must sum to 1 +/- 0.001.")
    if len(zone_cities) != 1:
        result.errors.append("Operational zones must share one nonempty city geography.")
    elif zone_cities:
        result.geography_level = "city"
        result.geography_name = next(iter(zone_cities))
        result.geography_id = "BGD-DHAKA-SOUTH" if result.geography_name == "Dhaka South" else result.geography_name

    facility_ids: list[str] = []
    zone_id_set = set(zone_ids)
    for index, facility in enumerate(facilities):
        label = f"facilities[{index}]"
        fid = str(facility.get("facility_id", "")).strip()
        if not fid:
            result.errors.append(f"{label}.facility_id must be nonempty.")
        facility_ids.append(fid)
        if str(facility.get("zone_id", "")).strip() not in zone_id_set:
            result.errors.append(f"{label}.zone_id does not reference an existing zone.")
        for field_name in ("facility_name", "facility_type"):
            if _is_blank(facility.get(field_name)):
                result.errors.append(f"{label}.{field_name} must be nonempty.")
        los = _number(facility, "avg_length_of_stay", label, result.errors)
        general = _number(facility, "general_bed_capacity", label, result.errors)
        dengue = _number(facility, "dengue_bed_capacity_demo", label, result.errors)
        occupied = _number(facility, "occupied_dengue_beds_demo", label, result.errors)
        baseline = _number(facility, "baseline_daily_dengue_cases_demo", label, result.errors)
        if los is not None and los <= 0:
            result.errors.append(f"{label}.avg_length_of_stay must be positive.")
        for field_name, value in (("general_bed_capacity", general), ("dengue_bed_capacity_demo", dengue), ("occupied_dengue_beds_demo", occupied), ("baseline_daily_dengue_cases_demo", baseline)):
            if value is not None and value < 0:
                result.errors.append(f"{label}.{field_name} must be nonnegative.")
        if occupied is not None and dengue is not None and occupied > dengue:
            result.errors.append(f"{label} occupancy exceeds dengue bed capacity.")
        if dengue is not None and general is not None and dengue > general:
            result.errors.append(f"{label} dengue bed capacity exceeds general capacity.")
    if len(set(facility_ids)) != len(facility_ids):
        result.errors.append("facility_id values must be unique.")

    inventory_ids: list[str] = []
    item_keys: list[tuple[str, str]] = []
    facility_id_set = set(facility_ids)
    for index, item in enumerate(inventory):
        label = f"inventory[{index}]"
        inventory_id = str(item.get("inventory_id", "")).strip()
        if inventory_id:
            inventory_ids.append(inventory_id)
        fid = str(item.get("facility_id", "")).strip()
        item_name = str(item.get("item_name", "")).strip()
        item_keys.append((fid, item_name))
        if fid not in facility_id_set:
            result.errors.append(f"{label}.facility_id does not reference a facility.")
        if not item_name:
            result.errors.append(f"{label}.item_name must be nonempty.")
        stock = _number(item, "current_stock", label, result.errors)
        consumption = _number(item, "baseline_daily_consumption", label, result.errors)
        threshold = _number(item, "reorder_threshold_days", label, result.errors)
        if stock is not None and stock < 0:
            result.errors.append(f"{label}.current_stock must be nonnegative.")
        if consumption is not None and consumption < 0:
            result.errors.append(f"{label}.baseline_daily_consumption must be nonnegative.")
        if threshold is not None and threshold <= 0:
            result.errors.append(f"{label}.reorder_threshold_days must be positive.")
    if len(set(inventory_ids)) != len(inventory_ids):
        result.errors.append("inventory_id values must be unique when present.")
    if len(set(item_keys)) != len(item_keys):
        result.errors.append("(facility_id, item_name) inventory keys must be unique.")

    descriptor = get_source_descriptor(expected_source) if expected_source else None
    if descriptor is None:
        statuses = {str(f.get("readiness_data_status", "")).strip() for f in facilities}
        if statuses and all(status.startswith("synthetic") for status in statuses):
            descriptor = get_source_descriptor("synthetic_demo")
    if descriptor:
        result.source_id, result.source_tag, result.source_class = descriptor.source_id, descriptor.canonical_tag, descriptor.source_class
    else:
        result.source_id, result.source_tag, result.source_class = "existing", "existing", "unknown"
        result.errors.append("Unable to determine a recognized operational source for reused inputs.")
    if expected_source == "synthetic_benchmark":
        _load_benchmark_metadata(result, paths[0])
    return result.finalize()


def validate_cross_source_compatibility(
    cases: DatasetValidation,
    climate: DatasetValidation,
    operational: DatasetValidation,
    *,
    allow_climate_spatial_proxy: bool = False,
    allow_mixed_epidemiology_inputs: bool = False,
    acknowledge_synthetic_operational_data: bool = False,
) -> CrossSourceValidation:
    result = CrossSourceValidation()
    if cases.errors or climate.errors or operational.errors:
        result.errors.append("Cross-source validation requires all domains to pass.")
        return result.finalize()

    overlap = sorted(set(cases.week_keys) & set(climate.week_keys))
    result.overlap_weeks = len(overlap)
    if not overlap:
        result.errors.append("Case and climate datasets have no epidemiological overlap.")
    else:
        result.start_period, result.end_period = overlap[0], overlap[-1]
        ordinals = [year * 52 + week for year, week in overlap]
        if any(ordinals[i] - ordinals[i - 1] != 1 for i in range(1, len(ordinals))):
            result.errors.append("Case/climate overlap is not contiguous.")
        if len(overlap) < MIN_OVERLAP_WEEKS:
            result.errors.append(f"Case/climate overlap has {len(overlap)} weeks; at least {MIN_OVERLAP_WEEKS} are required.")
        result.expected_supervised_rows = max(0, len(overlap) - FEATURE_BURN_IN_WEEKS - TARGET_HORIZON_WEEKS)
        if result.expected_supervised_rows < MIN_EXPECTED_SUPERVISED_ROWS:
            result.errors.append(f"Expected supervised history is {result.expected_supervised_rows} rows; at least {MIN_EXPECTED_SUPERVISED_ROWS} are required.")

    if cases.geography_id != climate.geography_id:
        if cases.geography_level == "national" and climate.geography_level in {"city", "point"}:
            result.errors.append("National case geography is incompatible with city or point climate geography.")
        elif cases.geography_level == "city" and climate.geography_level == "point" and climate.associated_geography_id == cases.geography_id:
            if allow_climate_spatial_proxy:
                result.overrides.append("allow_climate_spatial_proxy")
                result.warnings.append("Point climate accepted as an acknowledged city proxy.")
            else:
                result.errors.append("Point climate requires --allow-climate-spatial-proxy for city cases.")
        else:
            result.errors.append(f"Case geography '{cases.geography_id}' does not match climate geography '{climate.geography_id}'.")

    case_synthetic = cases.source_class == "synthetic"
    climate_synthetic = climate.source_class == "synthetic"
    if case_synthetic != climate_synthetic:
        if allow_mixed_epidemiology_inputs:
            result.overrides.append("allow_mixed_epidemiology_inputs")
            result.warnings.append("Synthetic and real epidemiology inputs were mixed.")
        else:
            result.errors.append("Synthetic and real case/climate inputs require --allow-mixed-epidemiology-inputs.")

    if not case_synthetic and not climate_synthetic and operational.source_class == "synthetic":
        if acknowledge_synthetic_operational_data:
            result.overrides.append("acknowledge_synthetic_operational_data")
            result.warnings.append("Synthetic operational inputs were acknowledged.")
        else:
            result.errors.append("Real case and climate inputs with synthetic operations require --acknowledge-synthetic-operational-data.")
    return result.finalize()


def _period_json(period: tuple[int, int] | None) -> dict[str, int] | None:
    return None if period is None else {"epi_year": period[0], "epi_week": period[1]}


def _dataset_manifest(result: DatasetValidation, selected_source: str) -> dict[str, Any]:
    value = {
        "selected_source": selected_source,
        "detected_source": result.source_id,
        "source_tag": result.source_tag,
        "source_class": result.source_class,
        "files": [{"path": _display_path(path), "sha256": result.file_hashes.get(_display_path(path))} for path in result.paths],
        "counts": result.counts,
        "period": {"start": _period_json(result.start_period), "end": _period_json(result.end_period)} if result.start_period else None,
        "geography": {"level": result.geography_level, "id": result.geography_id, "name": result.geography_name},
        "frequency": "weekly" if result.domain in {"cases", "climate"} else None,
        "units": result.units,
        "validation": {"status": result.status, "warnings": result.warnings},
    }
    if result.adapter_metadata:
        value["adapter_metadata"] = result.adapter_metadata
    return value


def build_input_manifest(
    plan: InputSourcePlan,
    cases: DatasetValidation,
    climate: DatasetValidation,
    operational: DatasetValidation,
    cross: CrossSourceValidation,
    *,
    run_id: str | None = None,
    created_at: str | None = None,
    governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    run_id = run_id or str(uuid.uuid4())
    created_at = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    synthetic_domains = [domain for domain, result in (("cases", cases), ("climate", climate), ("operational", operational)) if result.source_class == "synthetic"]
    synthetic_metadata: dict[str, Any] = {}
    if synthetic_domains:
        benchmark = next((result.adapter_metadata for result in (cases, climate, operational) if result.source_id == "synthetic_benchmark" and result.adapter_metadata), None)
        synthetic_metadata = (
            {"seed": benchmark["seed"], "scenario": benchmark["scenario"], "simulation_version": benchmark["simulation_version"], "domains": synthetic_domains}
            if benchmark else {"seed": 42, "scenario": "synthetic_demo", "domains": synthetic_domains}
        )
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": created_at,
        "inputs": {
            "cases": _dataset_manifest(cases, plan.case_source),
            "climate": _dataset_manifest(climate, plan.climate_source),
            "operational": _dataset_manifest(operational, plan.operational_source),
        },
        "cross_source_validation": {
            "status": cross.status,
            "overlap_weeks": cross.overlap_weeks,
            "expected_supervised_rows": cross.expected_supervised_rows,
            "period": {"start": _period_json(cross.start_period), "end": _period_json(cross.end_period)},
        },
        "warnings": cases.warnings + climate.warnings + operational.warnings + cross.warnings,
        "overrides": cross.overrides,
        "synthetic": synthetic_metadata,
    }
    if governance is not None:
        manifest["governance"] = dict(governance)
    return manifest


def write_manifest_atomic(manifest: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        return path
    except Exception:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
        raise


def validate_inputs_and_write_manifest(
    plan: InputSourcePlan,
    *,
    cases_path: str | Path = CASES_PATH,
    climate_path: str | Path = CLIMATE_PATH,
    zones_path: str | Path = ZONES_PATH,
    facilities_path: str | Path = FACILITIES_PATH,
    inventory_path: str | Path = INVENTORY_PATH,
    manifest_path: str | Path = MANIFEST_PATH,
    allow_climate_spatial_proxy: bool = False,
    allow_mixed_epidemiology_inputs: bool = False,
    acknowledge_synthetic_operational_data: bool = False,
    governance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    expected_cases = None if plan.reuse_existing else plan.case_source
    expected_climate = None if plan.reuse_existing else plan.climate_source
    expected_operational = None if plan.reuse_existing else plan.operational_source
    cases = validate_case_dataset(cases_path, expected_cases)
    climate = validate_climate_dataset(climate_path, expected_climate)
    operational = validate_operational_inputs(zones_path, facilities_path, inventory_path, expected_operational)
    errors = [f"[{result.domain}] {error}" for result in (cases, climate, operational) for error in result.errors]
    if errors:
        raise InputValidationError(errors)
    cross = validate_cross_source_compatibility(
        cases, climate, operational,
        allow_climate_spatial_proxy=allow_climate_spatial_proxy,
        allow_mixed_epidemiology_inputs=allow_mixed_epidemiology_inputs,
        acknowledge_synthetic_operational_data=acknowledge_synthetic_operational_data,
    )
    if cross.errors:
        raise InputValidationError([f"[cross-source] {error}" for error in cross.errors])
    manifest = build_input_manifest(plan, cases, climate, operational, cross, governance=governance)
    write_manifest_atomic(manifest, manifest_path)
    return manifest
