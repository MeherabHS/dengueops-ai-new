"""Fetch, cache, validate, and canonicalize NASA POWER daily point climate data."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_CSV = DATA_DIR / "climate_data.csv"
CACHE_CSV = RAW_DIR / "nasa_power_dhaka_south_daily_2014_2024.csv"
META_JSON = RAW_DIR / "nasa_power_dhaka_south_metadata.json"
LATITUDE, LONGITUDE = 23.7104, 90.4074
DEFAULT_START, DEFAULT_END = "2014-01-01", "2024-12-31"
NASA_POWER_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
DATASET_ID = "NASA POWER Daily Point"
COMMUNITY, TIME_STANDARD = "RE", "UTC"
PARAMETERS = ["PRECTOTCORR", "T2M", "RH2M", "T2M_MAX", "T2M_MIN", "QV2M"]
MODELED_PARAMETERS = ["PRECTOTCORR", "T2M", "RH2M"]
UNITS = {
    "PRECTOTCORR": "mm/day", "T2M": "degrees_celsius", "RH2M": "percent",
    "T2M_MAX": "degrees_celsius", "T2M_MIN": "degrees_celsius", "QV2M": "g/kg",
}
CANONICAL_COLUMNS = [
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "latitude", "longitude", "rainfall_mm", "avg_temp_c",
    "humidity_pct", "coverage_days", "source_type", "aggregation_method",
    "is_approximated", "associated_geography_level", "associated_geography_id",
    "associated_geography_name",
]
STALE_DAYS = 30


class AdapterError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _parse_nasa_response(payload: dict) -> pd.DataFrame:
    try:
        props = payload["properties"]["parameter"]
    except (KeyError, TypeError) as exc:
        raise AdapterError(f"Unexpected NASA POWER response structure: {exc}") from exc
    dates = sorted(props.get("T2M", {}))
    rows = []
    for key in dates:
        if len(key) != 8 or not key.isdigit():
            continue
        try:
            date = dt.datetime.strptime(key, "%Y%m%d").date()
        except ValueError:
            continue
        row: dict[str, Any] = {"date": date}
        for parameter in PARAMETERS:
            value = props.get(parameter, {}).get(key, float("nan"))
            row[parameter] = float("nan") if value is None or float(value) <= -998 else float(value)
        rows.append(row)
    if not rows:
        raise AdapterError("NASA POWER response contains no daily rows.")
    return pd.DataFrame(rows)


def fetch_from_nasa(start: str, end: str) -> pd.DataFrame:
    if requests is None:
        raise AdapterError("The requests package is required for NASA POWER fetching.")
    params = {
        "latitude": LATITUDE, "longitude": LONGITUDE,
        "start": start.replace("-", ""), "end": end.replace("-", ""),
        "community": COMMUNITY, "parameters": ",".join(PARAMETERS), "format": "JSON",
        "header": "true", "time-standard": TIME_STANDARD,
    }
    try:
        response = requests.get(NASA_POWER_URL, params=params, timeout=120)
        response.raise_for_status()
        return _parse_nasa_response(response.json())
    except Exception as exc:
        raise AdapterError(f"NASA POWER fetch failed: {exc}") from exc


def _validate_daily(df: pd.DataFrame) -> pd.DataFrame:
    required = {"date", *PARAMETERS}
    missing = required - set(df.columns)
    if missing:
        raise AdapterError(f"NASA cache missing required columns: {sorted(missing)}")
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    if out.empty or out["date"].isna().any():
        raise AdapterError("NASA cache contains no valid complete date series.")
    if out["date"].duplicated().any() or not out["date"].is_monotonic_increasing:
        raise AdapterError("NASA cache dates must be unique and sorted.")
    expected = pd.date_range(out["date"].iloc[0], out["date"].iloc[-1], freq="D")
    if len(expected) != len(out) or not out["date"].reset_index(drop=True).equals(pd.Series(expected)):
        raise AdapterError("NASA cache daily coverage is not contiguous.")
    for parameter in PARAMETERS:
        out[parameter] = pd.to_numeric(out[parameter], errors="coerce")
    return out


def _load_metadata(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AdapterError(f"NASA cache metadata is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise AdapterError("NASA cache metadata must be a JSON object.")
    return value


def validate_cache(cache_path: Path, metadata_path: Path, start: str, end: str) -> tuple[pd.DataFrame, dict, list[str]]:
    metadata = _load_metadata(metadata_path)
    if metadata.get("metadata_schema_version") != "1.0":
        raise AdapterError("NASA cache metadata schema is unsupported.")
    expected = {
        "adapter": "nasa_power", "endpoint": NASA_POWER_URL, "dataset_id": DATASET_ID,
        "community": COMMUNITY, "time_standard": TIME_STANDARD,
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise AdapterError(f"NASA cache metadata {key} mismatch.")
    coordinates = metadata.get("coordinates", {})
    if not math.isclose(float(coordinates.get("latitude", math.nan)), LATITUDE) or not math.isclose(float(coordinates.get("longitude", math.nan)), LONGITUDE):
        raise AdapterError("NASA cache coordinate mismatch.")
    if set(metadata.get("parameters", [])) != set(PARAMETERS):
        raise AdapterError("NASA cache parameter mismatch.")
    if metadata.get("units") != UNITS:
        raise AdapterError("NASA cache unit mismatch.")
    stored_path = Path(str(metadata.get("cache_file_path", "")))
    if not stored_path.is_absolute():
        stored_path = ROOT / stored_path
    if stored_path.resolve() != cache_path.resolve():
        raise AdapterError("NASA cache path mismatch.")
    if metadata.get("cache_file_sha256") != sha256_file(cache_path):
        raise AdapterError("NASA cache hash mismatch.")
    df = _validate_daily(pd.read_csv(cache_path))
    actual = {"start": df["date"].min().date().isoformat(), "end": df["date"].max().date().isoformat()}
    if metadata.get("actual_cached_range") != actual:
        raise AdapterError("NASA metadata coverage differs from actual cache coverage.")
    if start < actual["start"] or end > actual["end"]:
        raise AdapterError("NASA cache does not contain the requested range.")
    sliced = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    if sliced.empty:
        raise AdapterError("NASA requested cache slice is empty.")
    warnings: list[str] = []
    fetched = dt.datetime.fromisoformat(str(metadata["fetched_at"]).replace("Z", "+00:00"))
    if dt.datetime.now(dt.timezone.utc) - fetched > dt.timedelta(days=STALE_DAYS):
        warnings.append(f"Valid NASA POWER cache is older than {STALE_DAYS} days.")
    return sliced, metadata, warnings


def aggregate_to_weekly(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], list[str]]:
    daily = _validate_daily(df)
    iso = daily["date"].dt.isocalendar()
    daily["epi_year"], daily["epi_week"] = iso.year.astype(int), iso.week.astype(int)
    groups = list(daily.groupby(["epi_year", "epi_week"], sort=True))
    rows, excluded, warnings = [], [], []
    for index, ((year, week), group) in enumerate(groups):
        dates = group["date"].sort_values()
        monday = dt.date.fromisocalendar(int(year), int(week), 1)
        complete_dates = len(group) == 7 and dates.iloc[0].date() == monday and dates.iloc[-1].date() == monday + dt.timedelta(days=6)
        complete_values = all(group[p].notna().sum() == 7 and group[p].map(math.isfinite).all() for p in MODELED_PARAMETERS)
        if not complete_dates or not complete_values:
            if index in {0, len(groups) - 1} and not complete_dates:
                excluded.append(f"{year}-W{int(week):02d}")
                continue
            raise AdapterError(f"Incomplete interior NASA week {year}-W{int(week):02d}.")
        if int(week) == 53:
            raise AdapterError("NASA selected output contains week 53; the current engine supports weeks 1-52 only.")
        rows.append({
            "epi_year": int(year), "epi_week": int(week), "date_start": monday.isoformat(),
            "geography_level": "point", "geography_id": "nasa-power-23.7104-90.4074",
            "geography_name": "NASA POWER point at Dhaka South centroid",
            "latitude": LATITUDE, "longitude": LONGITUDE,
            "rainfall_mm": round(float(group["PRECTOTCORR"].sum()), 2),
            "avg_temp_c": round(float(group["T2M"].mean()), 2),
            "humidity_pct": round(float(group["RH2M"].mean()), 2), "coverage_days": 7,
            "source_type": "nasa_power", "aggregation_method": "daily_to_iso_weekly",
            "is_approximated": False, "associated_geography_level": "city",
            "associated_geography_id": "BGD-DHAKA-SOUTH", "associated_geography_name": "Dhaka South",
        })
    if excluded:
        warnings.append(f"Partial boundary weeks excluded: {', '.join(excluded)}")
    if not rows:
        raise AdapterError("NASA aggregation produced no complete weekly rows.")
    return pd.DataFrame(rows, columns=CANONICAL_COLUMNS), excluded, warnings


def _atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    except Exception:
        if Path(name).exists(): Path(name).unlink()
        raise


def _atomic_publish(files: list[tuple[Path, bytes]]) -> None:
    temporary: list[tuple[Path, Path]] = []
    try:
        for destination, content in files:
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
            temporary.append((Path(name), destination))
        for source, destination in temporary:
            os.replace(source, destination)
    except Exception:
        for source, _ in temporary:
            if source.exists(): source.unlink()
        raise


def _cache_metadata(df: pd.DataFrame, cache_path: Path, cache_hash: str, start: str, end: str, fetched_at: str) -> dict[str, Any]:
    return {
        "metadata_schema_version": "1.0", "adapter": "nasa_power", "endpoint": NASA_POWER_URL,
        "dataset_id": DATASET_ID, "community": COMMUNITY, "time_standard": TIME_STANDARD,
        "parameters": PARAMETERS, "coordinates": {"latitude": LATITUDE, "longitude": LONGITUDE},
        "requested_range": {"start": start, "end": end},
        "actual_cached_range": {"start": df["date"].min().date().isoformat(), "end": df["date"].max().date().isoformat()},
        "fetched_at": fetched_at, "cache_created_at": fetched_at,
        "cache_file_path": _display(cache_path), "cache_file_sha256": cache_hash,
        "rows": len(df), "units": UNITS,
    }


def main(start: str = DEFAULT_START, end: str = DEFAULT_END, force_refresh: bool = False,
         cache_csv: str | Path | None = None, cache_metadata: str | Path | None = None,
         output: str | Path | None = None, offline: bool = False) -> int:
    cache_path = Path(cache_csv) if cache_csv else CACHE_CSV
    metadata_path = Path(cache_metadata) if cache_metadata else META_JSON
    output_path = Path(output) if output else OUT_CSV
    try:
        if dt.date.fromisoformat(start) > dt.date.fromisoformat(end):
            raise AdapterError("start must not be after end.")
        used_cache, warnings = False, []
        daily = None
        if not force_refresh and cache_path.exists() and metadata_path.exists():
            try:
                daily, metadata, warnings = validate_cache(cache_path, metadata_path, start, end)
                used_cache = True
            except AdapterError:
                if offline:
                    raise
        if daily is None:
            if offline:
                raise AdapterError("Offline mode requires a compatible cache and metadata file.")
            fetched = _validate_daily(fetch_from_nasa(start, end))
            cache_bytes = fetched.to_csv(index=False).encode("utf-8")
            now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            metadata = _cache_metadata(fetched, cache_path, hashlib.sha256(cache_bytes).hexdigest(), start, end, now)
            weekly, excluded, aggregation_warnings = aggregate_to_weekly(fetched)
            warnings.extend(aggregation_warnings)
            output_bytes = weekly.to_csv(index=False).encode("utf-8")
            metadata.update({"cache_used": False, "weekly_output_range": {"start": weekly.iloc[0]["date_start"], "end": weekly.iloc[-1]["date_start"]},
                             "weekly_output_rows": len(weekly), "partial_boundary_weeks_excluded": excluded,
                             "warnings": ["NASA POWER is a public/nonofficial climate source.", *warnings],
                             "output_path": _display(output_path), "weekly_output_sha256": hashlib.sha256(output_bytes).hexdigest()})
            # Validate everything before replacing any prior file.
            _atomic_publish([
                (cache_path, cache_bytes),
                (metadata_path, (json.dumps(metadata, indent=2) + "\n").encode()),
                (output_path, output_bytes),
            ])
        else:
            weekly, excluded, aggregation_warnings = aggregate_to_weekly(daily)
            warnings.extend(aggregation_warnings)
            output_bytes = weekly.to_csv(index=False).encode("utf-8")
            metadata.update({"requested_range": {"start": start, "end": end}, "cache_used": True,
                             "weekly_output_range": {"start": weekly.iloc[0]["date_start"], "end": weekly.iloc[-1]["date_start"]},
                             "weekly_output_rows": len(weekly), "partial_boundary_weeks_excluded": excluded,
                             "warnings": ["NASA POWER is a public/nonofficial climate source.", *warnings],
                             "output_path": _display(output_path), "weekly_output_sha256": hashlib.sha256(output_bytes).hexdigest()})
            _atomic_publish([
                (metadata_path, (json.dumps(metadata, indent=2) + "\n").encode()),
                (output_path, output_bytes),
            ])
        for warning in metadata["warnings"]: print(f"[WARNING] {warning}")
        print(f"NASA POWER canonical output written: {output_path} ({len(weekly)} weeks; cache_used={used_cache})")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=DEFAULT_START); parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--force-refresh", action="store_true"); parser.add_argument("--cache-csv")
    parser.add_argument("--cache-metadata"); parser.add_argument("--output"); parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    sys.exit(main(args.start, args.end, args.force_refresh, args.cache_csv, args.cache_metadata, args.output, args.offline))
