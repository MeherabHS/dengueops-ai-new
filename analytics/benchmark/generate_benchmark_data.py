"""Offline deterministic generator for linked synthetic benchmark inputs."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from benchmark.config import BenchmarkConfig, periods_from_config, validate_config
    from benchmark.scenarios import INVALID_SUBTYPES, SCENARIOS, apply_scenario, build_expectations
else:
    from .config import BenchmarkConfig, periods_from_config, validate_config
    from .scenarios import INVALID_SUBTYPES, SCENARIOS, apply_scenario, build_expectations

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data"
CANONICAL_FILES = ("dengue_cases.csv", "climate_data.csv", "zones.json", "facilities.json", "inventory.json")
CASE_COLUMNS = (
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "city", "cases", "deaths", "deaths_data_status",
    "source_type", "is_approximated", "approximation_method",
)
CLIMATE_COLUMNS = (
    "epi_year", "epi_week", "date_start", "geography_level", "geography_id",
    "geography_name", "latitude", "longitude", "rainfall_mm", "avg_temp_c",
    "humidity_pct", "coverage_days", "source_type", "aggregation_method", "is_approximated",
)


def _fingerprint(config: BenchmarkConfig) -> str:
    payload = json.dumps(config.as_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _rngs(seed: int) -> dict[str, np.random.Generator]:
    names = ("climate", "latent_case", "observation", "death", "operational")
    return {name: np.random.default_rng(child) for name, child in zip(names, np.random.SeedSequence(seed).spawn(len(names)))}


def _climate(config: BenchmarkConfig, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    year_effects: dict[int, tuple[float, float]] = {}
    phase_shift = -7 if config.scenario == "early_surge" else 0
    for year, week, date_start in periods_from_config(config):
        if year not in year_effects:
            year_effects[year] = (rng.normal(0, 5.0), rng.normal(0, 0.45))
        rain_year, temp_year = year_effects[year]
        shared = rng.normal(0, 1)
        shifted = week - phase_shift
        monsoon = math.exp(-0.5 * ((shifted - 31) / 7.2) ** 2)
        early_shock = config.climate_shock_magnitude * math.exp(-0.5 * ((week - (20 if config.scenario == "early_surge" else 32)) / 5.0) ** 2)
        rain = max(0.0, 12 + 128 * monsoon + 105 * early_shock + rain_year + 10 * shared + rng.normal(0, 12))
        temp = 27.2 + 4.0 * math.sin(2 * math.pi * (week - 11) / 52) + temp_year + 0.35 * shared + rng.normal(0, 0.55)
        humidity = 50.5 + 0.205 * rain + 2.0 * shared + rng.normal(0, 2.4)
        rows.append({
            "epi_year": year, "epi_week": week, "date_start": date_start,
            "geography_level": config.geography_level, "geography_id": config.geography_id,
            "geography_name": config.geography_name, "latitude": config.latitude,
            "longitude": config.longitude, "rainfall_mm": round(rain, 2),
            "avg_temp_c": round(float(np.clip(temp, config.min_temperature_c, config.max_temperature_c)), 2),
            "humidity_pct": round(float(np.clip(humidity, config.min_humidity_pct, config.max_humidity_pct)), 2),
            "coverage_days": 7, "source_type": "synthetic_benchmark",
            "aggregation_method": "simulated_weekly_benchmark", "is_approximated": False,
        })
    return pd.DataFrame(rows, columns=CLIMATE_COLUMNS)


def _cases(config: BenchmarkConfig, climate: pd.DataFrame, rngs: dict[str, np.random.Generator]) -> tuple[pd.DataFrame, np.ndarray]:
    latent = np.zeros(len(climate), dtype=float)
    observed = np.zeros(len(climate), dtype=int)
    year_noise: dict[int, float] = {}
    suitability = []
    for row in climate.itertuples(index=False):
        rain = 1 - math.exp(-row.rainfall_mm / 75)
        temp = math.exp(-0.5 * ((row.avg_temp_c - 29.0) / 4.2) ** 2)
        humid = np.clip((row.humidity_pct - 35) / 50, 0, 1)
        suitability.append(0.44 * rain + 0.33 * temp + 0.23 * humid)
    for i, row in enumerate(climate.itertuples(index=False)):
        year_noise.setdefault(row.epi_year, rngs["latent_case"].normal(0, 0.08))
        lagged = np.mean([suitability[max(0, i - lag)] for lag in (2, 3, 4)])
        seasonal = 0.36 * math.sin(2 * math.pi * (row.epi_week - 27) / 52)
        shock = 0.0
        if config.scenario == "early_surge":
            shock = config.transmission_shock_magnitude * math.exp(-0.5 * ((row.epi_week - 26) / 5.5) ** 2)
        elif config.scenario == "severe_surge":
            shock = config.transmission_shock_magnitude * math.exp(-0.5 * ((row.epi_week - 38) / 8.0) ** 2)
            if i >= len(climate) - 16:
                shock += 0.75 * (i - (len(climate) - 16)) / 15
        previous = latent[i - 1] if i else 28.0
        log_mu = 2.55 + seasonal + config.climate_strength * 1.7 * lagged + config.autoregressive_strength * math.log1p(previous) + shock + year_noise[row.epi_year]
        latent[i] = min(15000.0, math.exp(log_mu))
        shape = config.observation_dispersion
        rate = rngs["observation"].gamma(shape, latent[i] / shape)
        observed[i] = int(rngs["observation"].poisson(rate))
    if config.scenario == "reporting_delay":
        delayed = np.zeros_like(observed)
        for i in range(len(observed)):
            prior = latent[max(0, i - config.reporting_delay_weeks)]
            delayed[i] = max(0, int(round(config.current_reporting_fraction * latent[i] + config.delayed_fraction * prior)))
        observed = delayed
    deaths = np.array([int(rngs["death"].binomial(int(value), config.death_rate)) for value in observed])
    rows = []
    for period, value, death in zip(periods_from_config(config), observed, deaths):
        year, week, date_start = period
        rows.append({
            "epi_year": year, "epi_week": week, "date_start": date_start,
            "geography_level": config.geography_level, "geography_id": config.geography_id,
            "geography_name": config.geography_name, "city": config.geography_name,
            "cases": int(value), "deaths": int(death), "deaths_data_status": "simulated",
            "source_type": "synthetic_benchmark", "is_approximated": False,
            "approximation_method": None,
        })
    return pd.DataFrame(rows, columns=CASE_COLUMNS), latent


def _operational(config: BenchmarkConfig, rng: np.random.Generator) -> tuple[list[dict], list[dict], list[dict]]:
    shares = (0.24, 0.21, 0.20, 0.18, 0.17)
    zones = []
    facilities = []
    inventory = []
    for z in range(1, 6):
        zid = f"BZ{z:02d}"
        zones.append({
            "zone_id": zid, "zone_name": f"Benchmark Zone {z}", "city": "Dhaka South",
            "population_share": shares[z - 1], "density_weight": round(0.48 + z * 0.075, 3),
            "facility_pressure_weight": round(0.38 + z * 0.09, 3),
            "mobility_corridor_weight": round(0.72 - z * 0.055, 3),
            "vulnerability_weight": round(0.34 + z * 0.105, 3),
            "exposure_index": round(0.41 + z * 0.095, 3),
            "current_anomaly_adjustment": round((z - 3) * 0.025, 3),
        })
        for local in range(1, 3):
            number = (z - 1) * 2 + local
            fid = f"BF{number:02d}"
            general = 48 + 7 * number
            dengue = 18 + 3 * number
            pressure = config.facility_pressure_fraction
            dengue = max(4, int(round(dengue * (1 - 1.6 * pressure))))
            occupied = min(dengue, int(round(dengue * (0.38 + 1.2 * pressure + rng.uniform(-0.03, 0.03)))))
            baseline = 3 + (number % 5)
            facilities.append({
                "facility_id": fid, "zone_id": zid, "facility_name": f"Synthetic Benchmark Facility {number:02d}",
                "facility_type": "Synthetic Benchmark Care Centre", "avg_length_of_stay": round(3.2 + 0.16 * number, 2),
                "general_bed_capacity": general, "dengue_bed_capacity_demo": dengue,
                "occupied_dengue_beds_demo": occupied, "baseline_daily_dengue_cases_demo": baseline,
                "facility_anchor_type": "wholly_synthetic_benchmark", "bed_capacity_source": "synthetic_benchmark_assumption",
                "readiness_data_status": "synthetic_benchmark_readiness", "inventory_data_status": "synthetic_benchmark_inventory",
                "notes": "Wholly synthetic benchmark facility; no real-world institution is represented.",
            })
            for code, item, multiplier, threshold in (("NS1", "NS1/RDT Kit", 1.0, 7), ("IVF", "IV Fluid (500ml)", 2.4, 5)):
                consumption = max(1, int(round(baseline * multiplier)))
                initial = consumption * (35 + number)
                consumed = consumption * 21
                endpoint = max(0, initial - consumed)
                endpoint = int(round(endpoint * (1 - config.stock_stress_fraction)))
                if config.replenishment_fraction:
                    endpoint += int(round(initial * config.replenishment_fraction))
                inventory.append({
                    "inventory_id": f"BINV-{fid}-{code}", "facility_id": fid, "item_name": item,
                    "current_stock": endpoint, "baseline_daily_consumption": consumption,
                    "reorder_threshold_days": threshold,
                })
    return zones, facilities, inventory


def _apply_invalid(bundle: dict[str, Any], subtype: str) -> None:
    if subtype == "missing_week":
        bundle["cases"] = bundle["cases"].drop(index=20).reset_index(drop=True)
    elif subtype == "duplicate_week":
        bundle["cases"] = pd.concat([bundle["cases"], bundle["cases"].iloc[[-1]]], ignore_index=True)
    elif subtype == "negative_cases":
        bundle["cases"].loc[10, "cases"] = -1
    elif subtype == "invalid_humidity":
        bundle["climate"].loc[10, "humidity_pct"] = 101.0
    elif subtype == "broken_facility_reference":
        bundle["inventory"][0]["facility_id"] = "MISSING-FACILITY"
    elif subtype == "occupancy_above_capacity":
        bundle["facilities"][0]["occupied_dengue_beds_demo"] = bundle["facilities"][0]["dengue_bed_capacity_demo"] + 1


def generate_benchmark(config: BenchmarkConfig) -> dict[str, Any]:
    config = validate_config(config)
    rngs = _rngs(config.seed)
    climate = _climate(config, rngs["climate"])
    cases, latent = _cases(config, climate, rngs)
    zones, facilities, inventory = _operational(config, rngs["operational"])
    fingerprint = _fingerprint(config)
    periods = periods_from_config(config)
    expectations = {
        "schema_version": "1.0", "simulation_version": config.simulation_version,
        "scenario": config.scenario, "seed": config.seed, "configuration_fingerprint": fingerprint,
        **build_expectations(config),
        "expected_peak_range": {"min_week": 18 if config.scenario == "early_surge" else 28, "max_week": 36 if config.scenario == "early_surge" else 50},
        "expected_peak_period": "earlier_monsoon" if config.scenario == "early_surge" else "monsoon_or_post_monsoon",
        "latent_summary": {"minimum": round(float(latent.min()), 3), "maximum": round(float(latent.max()), 3), "mean": round(float(latent.mean()), 3)},
    }
    bundle = {"config": config, "cases": cases, "climate": climate, "zones": zones, "facilities": facilities, "inventory": inventory, "expectations": expectations, "latent_cases": latent.copy(),
              "period": {"start": {"epi_year": periods[0][0], "epi_week": periods[0][1]}, "end": {"epi_year": periods[-1][0], "epi_week": periods[-1][1]}}, "fingerprint": fingerprint}
    if config.scenario == "messy_invalid":
        _apply_invalid(bundle, config.invalid_subtype or "")
    return bundle


def validate_bundle(bundle: dict[str, Any]) -> None:
    """Run the existing canonical validators against a generated bundle."""
    from input_validation import validate_case_dataset, validate_climate_dataset, validate_operational_inputs

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        _write_canonical_files(bundle, path)
        results = (
            validate_case_dataset(path / "dengue_cases.csv", None),
            validate_climate_dataset(path / "climate_data.csv", None),
            validate_operational_inputs(path / "zones.json", path / "facilities.json", path / "inventory.json", None),
        )
        errors = [f"[{r.domain}] {e}" for r in results for e in r.errors]
        if errors:
            raise ValueError("; ".join(errors))


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO(newline="")
    frame.to_csv(buffer, index=False, lineterminator="\n", na_rep="")
    return buffer.getvalue().encode("utf-8")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, separators=(",", ": ")) + "\n").encode("utf-8")


def _canonical_bytes(bundle: dict[str, Any]) -> dict[str, bytes]:
    return {
        "dengue_cases.csv": _csv_bytes(bundle["cases"]), "climate_data.csv": _csv_bytes(bundle["climate"]),
        "zones.json": _json_bytes(bundle["zones"]), "facilities.json": _json_bytes(bundle["facilities"]),
        "inventory.json": _json_bytes(bundle["inventory"]),
    }


def _write_canonical_files(bundle: dict[str, Any], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in _canonical_bytes(bundle).items():
        (output_dir / name).write_bytes(content)


def write_bundle_atomic(bundle: dict[str, Any], output_dir: str | Path) -> dict[str, Path]:
    config: BenchmarkConfig = bundle["config"]
    if config.scenario != "messy_invalid":
        validate_bundle(bundle)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    canonical = _canonical_bytes(bundle)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in canonical.items()}
    output_files = {name: f"data/{name}" for name in CANONICAL_FILES}
    metadata = {
        "metadata_schema_version": "1.0", "adapter": "synthetic_benchmark",
        "simulation_version": config.simulation_version, "config_version": config.config_version,
        "scenario": config.scenario, "seed": config.seed, "configuration": config.as_dict(),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "configuration_fingerprint": bundle["fingerprint"], "output_files": output_files,
        "output_hashes": hashes, "period": bundle["period"],
        "geography": {"level": config.geography_level, "id": config.geography_id, "name": config.geography_name, "latitude": config.latitude, "longitude": config.longitude},
        "expected_behavior_summary": build_expectations(config),
    }
    if config.scenario == "reporting_delay":
        metadata["reporting_delay_rule"] = {"current_reporting_fraction": config.current_reporting_fraction, "delayed_fraction": config.delayed_fraction, "delay_weeks": config.reporting_delay_weeks}
    files = {**canonical, "benchmark_expectations.json": _json_bytes(bundle["expectations"]), "raw/synthetic_benchmark_metadata.json": _json_bytes(metadata)}
    stage = Path(tempfile.mkdtemp(prefix=".benchmark-stage-", dir=output_dir))
    backup = Path(tempfile.mkdtemp(prefix=".benchmark-backup-", dir=output_dir))
    published: list[str] = []
    try:
        for relative, content in files.items():
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        for relative in files:
            destination = output_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                saved = backup / relative
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, saved)
            os.replace(stage / relative, destination)
            published.append(relative)
    except Exception:
        for relative in reversed(published):
            destination, saved = output_dir / relative, backup / relative
            if saved.exists():
                os.replace(saved, destination)
            elif destination.exists():
                destination.unlink()
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)
    return {relative: output_dir / relative for relative in files}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic synthetic benchmark inputs.")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--weeks", type=int, default=180)
    parser.add_argument("--start-year", type=int, default=2021)
    parser.add_argument("--start-week", type=int, default=1)
    parser.add_argument("--invalid-subtype", choices=INVALID_SUBTYPES)
    args = parser.parse_args()
    config = apply_scenario(BenchmarkConfig(seed=args.seed, number_of_weeks=args.weeks, start_year=args.start_year, start_week=args.start_week, invalid_subtype=args.invalid_subtype), args.scenario)
    write_bundle_atomic(generate_benchmark(config), DEFAULT_OUTPUT_DIR)
    print(f"Synthetic benchmark generated: {config.scenario}, seed={config.seed}, weeks={config.number_of_weeks}")


if __name__ == "__main__":
    main()
