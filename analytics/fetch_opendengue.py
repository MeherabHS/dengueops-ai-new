"""Fetch and canonicalize Bangladesh national OpenDengue monthly data."""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime
import hashlib
import io
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
OUT_FILE = DATA_DIR / "dengue_cases.csv"
RAW_FILE = DATA_DIR / "opendengue_bangladesh_raw.csv"
META_FILE = RAW_DIR / "opendengue_bangladesh_metadata.json"

ZIP_URL = "https://github.com/OpenDengue/master-repo/raw/main/data/releases/V1.3/National_extract_V1_3.zip"
DATASET_ID = "OpenDengue National Extract"
DATASET_VERSION = "1.3"
SOURCE_CITATION = "Clarke J, et al. OpenDengue: data from the OpenDengue database. Version 1.3. figshare; 2025."
APPROXIMATION_METHOD = "monthly_total_distributed_by_iso_week_overlap_days_with_midmonth_shape"
START_YEAR = 2014
END_YEAR = 2024
REQUIRED_RAW_COLUMNS = {"adm_0_name", "T_res", "Year", "dengue_total", "calendar_start_date"}
CANONICAL_COLUMNS = [
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "city", "cases", "deaths", "deaths_data_status",
    "source_type", "is_approximated", "approximation_method",
]


class AdapterError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _read_archive(input_zip: str | Path | None = None) -> tuple[list[dict], bytes]:
    if input_zip:
        try:
            archive = Path(input_zip).read_bytes()
        except OSError as exc:
            raise AdapterError(f"Cannot read OpenDengue ZIP: {exc}") from exc
    else:
        req = urllib.request.Request(ZIP_URL, headers={"User-Agent": "DengueOps/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                archive = response.read()
        except Exception as exc:
            raise AdapterError(f"OpenDengue download failed: {exc}") from exc
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zf:
            csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
            if not csv_names:
                raise AdapterError("OpenDengue ZIP contains no CSV file.")
            content = zf.read(csv_names[0])
    except AdapterError:
        raise
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        raise AdapterError(f"Invalid OpenDengue ZIP archive: {exc}") from exc
    try:
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames or not REQUIRED_RAW_COLUMNS.issubset(reader.fieldnames):
            missing = sorted(REQUIRED_RAW_COLUMNS - set(reader.fieldnames or []))
            raise AdapterError(f"OpenDengue CSV missing required columns: {missing}")
        rows = list(reader)
    except UnicodeError as exc:
        raise AdapterError(f"OpenDengue CSV is not valid UTF-8: {exc}") from exc
    return rows, content


def download_raw(
    input_zip: str | Path | None = None,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
) -> list[dict]:
    rows, _ = _read_archive(input_zip)
    selected: list[dict] = []
    for index, row in enumerate(rows, start=2):
        if row.get("adm_0_name", "").strip().upper() != "BANGLADESH" or row.get("T_res", "").strip() != "Month":
            continue
        try:
            year = int(row["Year"])
            float(row["dengue_total"])
            datetime.date.fromisoformat(row["calendar_start_date"])
        except (TypeError, ValueError, KeyError) as exc:
            raise AdapterError(f"Malformed relevant OpenDengue row {index}: {exc}") from exc
        if start_year <= year <= end_year and row["dengue_total"].strip() not in {"", "NA", "None"}:
            selected.append(row)
    if not selected:
        raise AdapterError("No Bangladesh monthly rows matched the requested range.")
    return selected


def month_to_epi_weeks(year: int, month: int, monthly_total: float) -> list[dict]:
    _, days_in_month = calendar.monthrange(year, month)
    buckets: dict[tuple[int, int], float] = {}
    current = datetime.date(year, month, 1)
    last = datetime.date(year, month, days_in_month)
    while current <= last:
        iso_year, iso_week, _ = current.isocalendar()
        buckets[(iso_year, iso_week)] = buckets.get((iso_year, iso_week), 0) + 1
        current += datetime.timedelta(days=1)
    total_days = sum(buckets.values())
    shapes = [0.9, 1.1, 1.1, 0.9]
    result = []
    for index, (iso_year, iso_week) in enumerate(sorted(buckets)):
        cases = max(0, round(monthly_total * buckets[(iso_year, iso_week)] / total_days * shapes[min(index, 3)]))
        result.append({"epi_year": iso_year, "epi_week": iso_week, "dengue_cases": cases})
    return result


def convert_to_weekly(rows: list[dict]) -> list[dict]:
    weekly: dict[tuple[int, int], dict] = {}
    for row in rows:
        start = datetime.date.fromisoformat(row["calendar_start_date"])
        for value in month_to_epi_weeks(int(row["Year"]), start.month, float(row["dengue_total"])):
            key = value["epi_year"], value["epi_week"]
            if key in weekly:
                weekly[key]["dengue_cases"] += value["dengue_cases"]
            else:
                weekly[key] = value
    return sorted(weekly.values(), key=lambda row: (row["epi_year"], row["epi_week"]))


def _canonical_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        year, week = int(row["epi_year"]), int(row["epi_week"])
        output.append({
            "epi_year": year, "epi_week": week,
            "date_start": datetime.date.fromisocalendar(year, week, 1).isoformat(),
            "geography_level": "national", "geography_id": "BGD",
            "geography_name": "Bangladesh", "city": "Bangladesh",
            "cases": int(row["dengue_cases"]), "deaths": None,
            "deaths_data_status": "unavailable_from_source", "source_type": "opendengue",
            "is_approximated": True, "approximation_method": APPROXIMATION_METHOD,
        })
    return output


def validate_canonical(rows: list[dict]) -> None:
    if not rows:
        raise AdapterError("OpenDengue conversion produced no weekly observations.")
    if any(set(row) != set(CANONICAL_COLUMNS) for row in rows):
        raise AdapterError("OpenDengue canonical output columns are invalid.")
    if any(int(row["epi_week"]) == 53 for row in rows):
        raise AdapterError("OpenDengue selected output contains week 53; the current engine supports weeks 1-52 only.")
    if any(row["source_type"] != "opendengue" or row["geography_id"] != "BGD" for row in rows):
        raise AdapterError("OpenDengue canonical source/geography values are invalid.")


def _csv_bytes(rows: list[dict], fieldnames: list[str]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _atomic_publish(files: list[tuple[Path, bytes]]) -> None:
    temporary: list[tuple[Path, Path]] = []
    try:
        for destination, content in files:
            destination.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.append((Path(name), destination))
        for source, destination in temporary:
            os.replace(source, destination)
    except Exception:
        for source, _ in temporary:
            if source.exists():
                source.unlink()
        raise


def main(
    input_zip: str | Path | None = None,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR,
    output_dir: str | Path | None = None,
) -> int:
    try:
        if start_year > end_year:
            raise AdapterError("start-year must not exceed end-year.")
        rows = download_raw(input_zip, start_year, end_year)
        # Preserve compatibility with tests that patch download_raw only.
        if not rows:
            raise AdapterError("No Bangladesh monthly rows matched the requested range.")
        weekly = _canonical_rows(convert_to_weekly(rows))
        validate_canonical(weekly)
        if output_dir:
            base = Path(output_dir)
            output_path = base / "dengue_cases.csv"
            raw_path = base / "opendengue_bangladesh_raw.csv"
            metadata_path = base / "raw" / "opendengue_bangladesh_metadata.json"
        else:
            output_path, raw_path, metadata_path = Path(OUT_FILE), Path(RAW_FILE), Path(META_FILE)
        raw_bytes = _csv_bytes(rows, list(rows[0].keys()))
        output_bytes = _csv_bytes(weekly, CANONICAL_COLUMNS)
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        metadata = {
            "metadata_schema_version": "1.0", "adapter": "opendengue",
            "dataset_id": DATASET_ID, "dataset_version": DATASET_VERSION,
            "source_url": str(Path(input_zip).resolve()) if input_zip else ZIP_URL,
            "source_citation": SOURCE_CITATION, "fetched_at": now,
            "raw_file_path": _display(raw_path), "raw_file_sha256": _sha256_bytes(raw_bytes),
            "requested_country": "Bangladesh", "requested_admin_level": "national",
            "requested_year_start": start_year, "requested_year_end": end_year,
            "original_temporal_resolution": "monthly", "approximation_method": APPROXIMATION_METHOD,
            "approximation_description": "Monthly national totals are distributed across intersecting ISO weeks using overlap days and the existing positional mid-month shape adjustment.",
            "output_path": _display(output_path), "output_sha256": _sha256_bytes(output_bytes),
            "output_start": {"epi_year": weekly[0]["epi_year"], "epi_week": weekly[0]["epi_week"]},
            "output_end": {"epi_year": weekly[-1]["epi_year"], "epi_week": weekly[-1]["epi_week"]},
            "output_rows": len(weekly),
        }
        meta_bytes = (json.dumps(metadata, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        _atomic_publish([(raw_path, raw_bytes), (output_path, output_bytes), (metadata_path, meta_bytes)])
        print(f"OpenDengue canonical output written: {output_path} ({len(weekly)} weeks)")
        print("[WARNING] OpenDengue monthly totals were approximated to weekly observations.")
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-zip")
    parser.add_argument("--start-year", type=int, default=START_YEAR)
    parser.add_argument("--end-year", type=int, default=END_YEAR)
    parser.add_argument("--output-dir")
    args = parser.parse_args()
    sys.exit(main(args.input_zip, args.start_year, args.end_year, args.output_dir))
