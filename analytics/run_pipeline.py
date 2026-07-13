"""
run_pipeline.py
===============
DengueOps AI — Phase 6: Full Pipeline Runner

One-command orchestrator for the complete DengueOps AI analytics pipeline.
Runs all 7 stages in order, validates expected outputs after each step,
and saves a structured run log.

Usage:
    python analytics/run_pipeline.py
        Run the full pipeline (all 7 steps).

    python analytics/run_pipeline.py --skip-data-generation
        Skip all input producers and reuse existing CSV/JSON input files.

    python analytics/run_pipeline.py --validate-only
        Check whether all required output files exist and are well-formed.
        Does not run any pipeline steps.

    python analytics/run_pipeline.py --export-dashboard-only
        Run only Step 7 (dashboard_exporter.py) using existing outputs.

Pipeline steps:
    1. generate_demo_data.py   → dengue_cases.csv, climate_data.csv, zones.json,
                                  facilities.json, inventory.json
    2. feature_engineering.py  → model_features.csv
    3. validation_backtest.py  → validation_metrics.json
    4. forecast_model.py       → forecast_output.json
    5. uncertainty_engine.py   → forecast_output.json (updated with scenarios)
    6. operational_engine.py   → directives.json
    7. dashboard_exporter.py   → dashboard_summary.json, model_comparison.json,
                                  chart_data.json

Outputs:
    data/pipeline_run_summary.json  — Structured run log
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from input_sources import (
    CASE_SOURCES,
    CLIMATE_SOURCES,
    OPERATIONAL_SOURCES,
    InputSourcePlan,
    SourcePlanError,
    resolve_input_plan,
)
from input_validation import (
    MANIFEST_PATH,
    InputValidationError,
    validate_inputs_and_write_manifest,
)
from provenance import (
    artifact_provenance,
    assert_same_provenance,
    derive_data_mode,
    load_compact_provenance,
    provenance_from_feature_frame,
)
from benchmark.config import BenchmarkConfig, validate_config
from benchmark.scenarios import INVALID_SUBTYPES, SCENARIOS, apply_scenario
from formula_registry import DEPLOYMENT_GATES, FormulaRegistryError, load_formula_registry
from evidence_registry import EvidenceRegistryError, load_evidence_registry, validate_formula_evidence_links
from deployment_profiles import (
    DeploymentProfileError, build_profile_provenance, load_deployment_profile,
    resolve_profile_run_configuration,
)
from explainability_engine import validate_model_explainability, validate_selected_model_explainability
from validation_backtest import validate_rolling_validation
from model_candidates import (OUTPUT_PATH as CANDIDATE_COMPARISON_PATH,
    REGISTRY_PATH as CANDIDATE_REGISTRY_PATH, validate_comparison_artifact)
from uncertainty_engine import validate_committed_bundle

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT          = Path(__file__).resolve().parent.parent
ANALYTICS_DIR = ROOT / "analytics"
DATA_DIR      = ROOT / "data"
RUN_SUMMARY_PATH = DATA_DIR / "pipeline_run_summary.json"
P13_TRANSACTION_PATHS = [DATA_DIR / name for name in (
    "input_manifest.json", "model_features.csv", "validation_metrics.json", "rolling_validation.json",
    "model_explainability.json", "candidate_model_comparison.json", "selected_model_explainability.json",
    "forecast_uncertainty.json", "forecast_output.json",
    "directives.json", "dashboard_summary.json", "model_comparison.json", "chart_data.json",
    "pipeline_run_summary.json", "model_card.json")]


def _replace_exact(path: Path, payload: bytes) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.transaction.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def _restore_transaction(snapshot: dict[Path, bytes | None]) -> None:
    for path, payload in snapshot.items():
        if payload is None:
            if path.exists(): path.unlink()
        else:
            _replace_exact(path, payload)

# ── Pipeline step definitions ─────────────────────────────────────────────────

ANALYTICS_STEPS: list[dict] = [
    # Step 1 — Default: controlled synthetic Dhaka South demo data
    # Use --use-opendengue to replace dengue_cases.csv with real Bangladesh data
    # Use --use-nasa-power-climate to replace climate_data.csv with NASA POWER data
    # ── Analytic steps (always run after data generation) ───────────────────
    {
        "id":          "feature_engineering",
        "script":      ANALYTICS_DIR / "feature_engineering.py",
        "description": "Phase 2 — Building lag-aware feature matrix",
        "skippable":   False,
        "expected_files": [DATA_DIR / "model_features.csv"],
    },
    {
        "id":          "validation_backtest",
        "script":      ANALYTICS_DIR / "validation_backtest.py",
        "description": "Phase 3a — Temporal backtest and model comparison",
        "skippable":   False,
        "expected_files": [DATA_DIR / "validation_metrics.json", DATA_DIR / "rolling_validation.json"],
    },
    {
        "id":          "forecast_model",
        "script":      ANALYTICS_DIR / "forecast_model.py",
        "description": "Phase 3b — Training final model and generating forecast",
        "skippable":   False,
        "expected_files": [DATA_DIR / "forecast_output.json"],
    },
    {
        "id":          "uncertainty_engine",
        "script":      ANALYTICS_DIR / "uncertainty_engine.py",
        "description": "P1.3 — Validating temporal empirical forecast range",
        "skippable":   False,
        "expected_files": [DATA_DIR / "forecast_output.json", DATA_DIR / "forecast_uncertainty.json"],
        "json_checks": {
            DATA_DIR / "forecast_output.json": ["forecast_uncertainty", "preparedness_scenarios", "uncertainty_scenarios"],
            DATA_DIR / "forecast_uncertainty.json": ["historical_evaluation", "future_forecast_interval", "provenance"],
        },
    },
    {
        "id":          "operational_engine",
        "script":      ANALYTICS_DIR / "operational_engine.py",
        "description": "Phase 5 — Building zone/facility operational directives",
        "skippable":   False,
        "expected_files": [DATA_DIR / "directives.json"],
        "json_checks": {
            DATA_DIR / "directives.json": ["directives", "summary"],
        },
    },
    {
        "id":          "dashboard_exporter",
        "script":      ANALYTICS_DIR / "dashboard_exporter.py",
        "description": "Phase 6 — Exporting dashboard-ready JSON files",
        "skippable":   False,
        "expected_files": [
            DATA_DIR / "dashboard_summary.json",
            DATA_DIR / "model_comparison.json",
            DATA_DIR / "chart_data.json",
        ],
    },
]

# ── Optional real-data steps (injected dynamically, not in default run) ───────
#
# These are experimental/future validation pathways. The default pipeline uses
# controlled synthetic data from generate_demo_data.py which is better suited
# for demonstrating the forecast-to-preparedness workflow.

# OpenDengue real Bangladesh data — replaces dengue_cases.csv
# All files that must exist for a fully valid pipeline run
ALL_OUTPUT_FILES: list[Path] = [
    DATA_DIR / "dengue_cases.csv",
    DATA_DIR / "climate_data.csv",
    MANIFEST_PATH,
    DATA_DIR / "model_features.csv",
    DATA_DIR / "validation_metrics.json",
    DATA_DIR / "rolling_validation.json",
    DATA_DIR / "forecast_output.json",
    DATA_DIR / "directives.json",
    DATA_DIR / "dashboard_summary.json",
    DATA_DIR / "model_comparison.json",
    DATA_DIR / "chart_data.json",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _banner(text: str, width: int = 66) -> None:
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)


def _step_header(step_num: int, total: int, description: str) -> None:
    print()
    print(f"  [{step_num}/{total}] {description}")
    print(f"  {'-' * 62}")


def _load_json_safe(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _validate_file(path: Path, json_keys: list[str] | None = None) -> str | None:
    """
    Check a single output file. Returns an error string or None if valid.
    """
    if not path.exists():
        return f"Missing: {path.name}"

    suffix = path.suffix.lower()

    if suffix == ".json":
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return f"Invalid JSON in {path.name}: {e}"
        if json_keys:
            for key in json_keys:
                if key not in data:
                    return f"{path.name}: missing required key '{key}'"

    elif suffix == ".csv":
        try:
            df = pd.read_csv(path, nrows=1)
            if len(df.columns) == 0:
                return f"{path.name}: no columns found"
        except Exception as e:
            return f"Cannot read {path.name}: {e}"

    return None   # valid


def _validate_step_outputs(step: dict) -> list[str]:
    """Validate all expected outputs for a pipeline step."""
    errors: list[str] = []
    for fp in step.get("expected_files", []):
        err = _validate_file(fp)
        if err:
            errors.append(err)

    # Extra JSON key checks
    for fp, keys in step.get("json_checks", {}).items():
        err = _validate_file(fp, json_keys=keys)
        if err:
            errors.append(err)

    return errors


# ── --validate-only ───────────────────────────────────────────────────────────

def cmd_validate_only() -> int:
    """
    Check whether all required output files exist and are well-formed.
    Returns 0 if everything passes, 1 if any check fails.
    """
    _banner("DengueOps AI — Validate Pipeline Outputs")
    print()
    print("  Checking all required output files...\n")

    all_errors: list[str] = []

    checks: list[tuple[Path, list[str] | None]] = [
        (DATA_DIR / "dengue_cases.csv",       None),
        (DATA_DIR / "climate_data.csv",        None),
        (MANIFEST_PATH, ["schema_version", "run_id", "inputs", "cross_source_validation"]),
        (DATA_DIR / "model_features.csv",      None),
        (DATA_DIR / "validation_metrics.json", ["metrics", "best_model", "actual_vs_predicted"]),
        (DATA_DIR / "rolling_validation.json", ["folds", "aggregate_metrics", "provenance"]),
        (DATA_DIR / "forecast_output.json",    ["forecast_cases", "forecast_uncertainty", "preparedness_scenarios"]),
        (DATA_DIR / "forecast_uncertainty.json", ["historical_evaluation", "future_forecast_interval", "provenance"]),
        (DATA_DIR / "directives.json",         ["directives", "summary"]),
        (DATA_DIR / "dashboard_summary.json",  ["headline_metrics", "uncertainty", "model_evidence"]),
        (DATA_DIR / "model_comparison.json",   ["models", "best_model"]),
        (DATA_DIR / "chart_data.json",         ["actual_vs_predicted", "zone_priority"]),
    ]
    manifest_value = _load_json_safe(MANIFEST_PATH)
    profiled_validation = bool(manifest_value and manifest_value.get("governance", {}).get("deployment_profile_id"))
    if profiled_validation:
        checks.append((DATA_DIR / "model_card.json", ["model_card_id", "deployment_id", "provenance"]))
        checks.append((DATA_DIR / "model_explainability.json", ["availability_status", "feature_ranking", "provenance"]))
        checks.append((DATA_DIR / "selected_model_explainability.json", ["availability_status", "feature_ranking", "provenance"]))

    for path, keys in checks:
        err = _validate_file(path, json_keys=keys)
        status = "[PASS]" if err is None else "[FAIL]"
        print(f"    {status}  {path.name}")
        if err:
            print(f"           {err}")
            all_errors.append(err)

    if not all_errors:
        try:
            expected = load_compact_provenance(MANIFEST_PATH)
            features = provenance_from_feature_frame(pd.read_csv(DATA_DIR / "model_features.csv"), MANIFEST_PATH)
            artifacts = []
            labels = []
            names = ["validation_metrics.json", "rolling_validation.json", "forecast_output.json", "forecast_uncertainty.json", "directives.json", "dashboard_summary.json", "pipeline_run_summary.json", "model_comparison.json", "chart_data.json"]
            if profiled_validation:
                names.append("model_card.json")
                names.append("model_explainability.json")
                names.append("selected_model_explainability.json")
            for name in names:
                value = _load_json_safe(DATA_DIR / name)
                if not value:
                    raise ValueError(f"Cannot load {name} for provenance validation.")
                artifacts.append(artifact_provenance(value, name)); labels.append(name)
            assert_same_provenance(expected, features, *artifacts, labels=("manifest", "model_features.csv", *labels))
            if profiled_validation:
                explainability_path = DATA_DIR / "model_explainability.json"
                explainability_bytes = explainability_path.read_bytes()
                explainability = json.loads(explainability_bytes.decode("utf-8"))
                model_card = _load_json_safe(DATA_DIR / "model_card.json")
                validation = _load_json_safe(DATA_DIR / "validation_metrics.json")
                feature_frame = pd.read_csv(DATA_DIR / "model_features.csv")
                cutoff = int(len(feature_frame) * 0.80)
                validate_model_explainability(
                    explainability,
                    expected_provenance=expected,
                    expected_feature_names=validation["features_used"],
                    expected_validation_df=feature_frame.iloc[cutoff:].copy(),
                    expected_target=validation["target"],
                )
                selected_path = DATA_DIR / "selected_model_explainability.json"
                selected_bytes = selected_path.read_bytes()
                selected = json.loads(selected_bytes.decode("utf-8"))
                validate_selected_model_explainability(
                    selected, expected_provenance=expected,
                    expected_feature_names=validation["features_used"],
                    expected_validation_df=feature_frame.iloc[cutoff:].copy(),
                    expected_comparison_sha256=model_card["comparison_artifact_sha256"],
                    expected_registry_sha256=model_card["candidate_registry_sha256"],
                )
                if hashlib.sha256(selected_bytes).hexdigest() != model_card["selected_model_explainability_artifact_sha256"]:
                    raise ValueError("Selected-model explainability hash differs from model-card commit record.")
                if hashlib.sha256((DATA_DIR / "forecast_output.json").read_bytes()).hexdigest() != model_card["forecast_artifact_sha256"]:
                    raise ValueError("Forecast hash differs from model-card commit record.")
                uncertainty_path = DATA_DIR / "forecast_uncertainty.json"
                uncertainty_bytes = uncertainty_path.read_bytes()
                forecast_bytes = (DATA_DIR / "forecast_output.json").read_bytes()
                validate_committed_bundle(
                    json.loads(forecast_bytes), json.loads(uncertainty_bytes), model_card,
                    uncertainty_bytes, forecast_bytes)
                rolling_path = DATA_DIR / "rolling_validation.json"
                rolling_bytes = rolling_path.read_bytes()
                rolling = json.loads(rolling_bytes.decode("utf-8"))
                validate_rolling_validation(
                    rolling, expected_df=feature_frame, expected_provenance=expected,
                    expected_model_card=model_card,
                    expected_artifact_sha256=hashlib.sha256(rolling_bytes).hexdigest(),
                )
                selection_status = model_card.get("model_selection_status")
                if selection_status == "comparison_complete_and_adopted":
                    if not CANDIDATE_COMPARISON_PATH.is_file():
                        raise ValueError("Model card requires missing candidate comparison artifact.")
                    comparison_bytes = CANDIDATE_COMPARISON_PATH.read_bytes()
                    comparison = json.loads(comparison_bytes.decode("utf-8"))
                    validate_comparison_artifact(comparison,
                        expected_registry_sha256=hashlib.sha256(CANDIDATE_REGISTRY_PATH.read_bytes()).hexdigest(),
                        expected_rolling_sha256=hashlib.sha256(rolling_bytes).hexdigest(), expected_rolling=rolling,
                        expected_model_card=model_card,
                        expected_artifact_sha256=hashlib.sha256(comparison_bytes).hexdigest())
                    assert_same_provenance(expected, artifact_provenance(comparison, "candidate_model_comparison.json"),
                                           labels=("manifest", "candidate_model_comparison.json"))
                elif CANDIDATE_COMPARISON_PATH.exists():
                    raise ValueError("Stale candidate comparison artifact exists for a not-run model card.")
            print("    [PASS]  manifest and artifact provenance")
        except Exception as exc:
            error = f"Provenance validation failed: {exc}"
            print(f"    [FAIL]  {error}")
            all_errors.append(error)

    print()
    if all_errors:
        print(f"  {len(all_errors)} check(s) failed.")
        print("  Run: python analytics/run_pipeline.py  to regenerate missing files.")
        return 1
    else:
        print("  All checks passed.")
        return 0


# ── Core pipeline runner ──────────────────────────────────────────────────────

DOMAIN_OUTPUTS: dict[str, tuple[Path, ...]] = {
    "cases": (DATA_DIR / "dengue_cases.csv",),
    "climate": (DATA_DIR / "climate_data.csv",),
    "operational": (
        DATA_DIR / "zones.json",
        DATA_DIR / "facilities.json",
        DATA_DIR / "inventory.json",
    ),
}


def build_input_steps(plan: InputSourcePlan) -> list[dict]:
    """Translate a fully resolved source plan into executable producer steps."""
    descriptions = {
        "generate_benchmark_data": "Phase 1 - Generating synthetic benchmark inputs",
        "generate_demo_data": "Phase 1 — Generating selected synthetic demo inputs",
        "fetch_opendengue": "Phase 1 — Fetching OpenDengue case data",
        "fetch_nasa_power_climate": "Phase 1 — Fetching NASA POWER climate data",
    }
    steps: list[dict] = []
    for producer in plan.producers:
        expected_files = [
            path
            for domain in producer.domains
            for path in DOMAIN_OUTPUTS[domain]
        ]
        steps.append({
            "id": producer.producer_id,
            "script": ANALYTICS_DIR / producer.script_name,
            "args": list(producer.args),
            "description": descriptions[producer.producer_id],
            "expected_files": expected_files,
        })
    return steps


def build_input_validation_step() -> dict:
    """Return the in-process validation stage placed before feature engineering."""
    return {
        "id": "input_validation",
        "description": "Phase 1b — Validating canonical inputs and writing manifest",
        "expected_files": [MANIFEST_PATH],
        "internal": True,
    }


def run_step(step: dict, cwd: Path) -> tuple[bool, float]:
    """
    Execute a pipeline step via subprocess.
    Returns (success: bool, elapsed_seconds: float).
    """
    t0 = time.perf_counter()
    environment = os.environ.copy()
    environment.update(step.get("env", {}))
    result = subprocess.run(
        [sys.executable, str(step["script"]), *step.get("args", [])],
        cwd=str(cwd),
        env=environment,
    )
    elapsed = time.perf_counter() - t0
    return result.returncode == 0, elapsed


def run_pipeline(
    skip_data_generation: bool = False,
    export_only: bool = False,
    use_nasa_power_climate: bool = False,
    use_opendengue: bool = False,
    case_source: str | None = None,
    climate_source: str | None = None,
    operational_source: str | None = None,
    allow_climate_spatial_proxy: bool = False,
    allow_mixed_epidemiology_inputs: bool = False,
    acknowledge_synthetic_operational_data: bool = False,
    benchmark_scenario: str | None = None,
    benchmark_seed: int | None = None,
    benchmark_weeks: int | None = None,
    benchmark_start_year: int | None = None,
    benchmark_start_week: int | None = None,
    benchmark_invalid_subtype: str | None = None,
    benchmark_options_explicit: bool = False,
    deployment_gate: str | None = None,
    deployment_profile: str | None = None,
    run_model_comparison: bool = False,
) -> int:
    """
    Execute the pipeline. Returns 0 on success, 1 on failure.

    Default mode uses controlled synthetic Dhaka South demo data (2024–2026).
    Optional real-data pathways are available via flags but are not the default.

    Args:
        skip_data_generation:   Skip every input producer and reuse files.
        export_only:            Run only dashboard_exporter.
        use_nasa_power_climate: [Experimental] Replace synthetic climate_data.csv
                                with real NASA POWER data.
        use_opendengue:         [Experimental] Replace synthetic dengue_cases.csv
                                with real OpenDengue Bangladesh national data.
    """
    source_options_used = any(
        value is not None
        for value in (case_source, climate_source, operational_source)
    ) or use_opendengue or use_nasa_power_climate or benchmark_options_explicit or any((
        allow_climate_spatial_proxy,
        allow_mixed_epidemiology_inputs,
        acknowledge_synthetic_operational_data,
    ))
    if export_only and (skip_data_generation or source_options_used):
        print(
            "[ERROR] --export-dashboard-only cannot be combined with input "
            "source or generation options."
        )
        return 2

    profile: dict[str, Any] | None = None
    governance: dict[str, Any] | None = None
    try:
        formula_registry = load_formula_registry()
        evidence_registry = load_evidence_registry()
        validate_formula_evidence_links(evidence_registry, formula_registry)
        if deployment_profile:
            profile = load_deployment_profile(deployment_profile)
            governance = build_profile_provenance(profile)
            if (profile.get("candidate_comparison", {}).get("selected_model_adoption_status") == "adopted_p1.2b"
                    and not run_model_comparison and not export_only):
                raise DeploymentProfileError(
                    "P1.2B governed adoption requires --run-model-comparison; stale comparison evidence is prohibited."
                )
            if skip_data_generation or export_only:
                existing = load_compact_provenance(MANIFEST_PATH)
                if existing.get("deployment_profile_sha256") != governance["deployment_profile_sha256"]:
                    mode = "--skip-data-generation" if skip_data_generation else "--export-dashboard-only"
                    raise DeploymentProfileError(f"{mode} requires an existing manifest with the same deployment profile binding.")
                deployment_gate = deployment_gate or profile["deployment_gate"]
                if deployment_gate != profile["deployment_gate"]:
                    raise DeploymentProfileError("CLI deployment gate conflicts with the existing deployment profile.")
            else:
                resolved = resolve_profile_run_configuration(profile, {
                    "case_source": case_source,
                    "climate_source": climate_source,
                    "operational_source": operational_source,
                    "deployment_gate": deployment_gate,
                })
                case_source = resolved["case_source"]
                climate_source = resolved["climate_source"]
                operational_source = resolved["operational_source"]
                deployment_gate = resolved["deployment_gate"]
        deployment_gate = deployment_gate or "benchmark_only"
        if deployment_gate not in DEPLOYMENT_GATES:
            raise FormulaRegistryError(f"Unknown deployment gate: {deployment_gate}.")
        benchmark_selected = any(source == "synthetic_benchmark" for source in (case_source, climate_source, operational_source))
        benchmark_args: tuple[str, ...] = ()
        if benchmark_selected or benchmark_options_explicit:
            scenario = benchmark_scenario or "normal"
            seed = 42 if benchmark_seed is None else benchmark_seed
            weeks = 180 if benchmark_weeks is None else benchmark_weeks
            start_year = 2021 if benchmark_start_year is None else benchmark_start_year
            start_week = 1 if benchmark_start_week is None else benchmark_start_week
            config = apply_scenario(BenchmarkConfig(seed=seed, number_of_weeks=weeks, start_year=start_year, start_week=start_week, invalid_subtype=benchmark_invalid_subtype), scenario)
            validate_config(config)
            benchmark_args = (
                "--scenario", scenario, "--seed", str(seed), "--weeks", str(weeks),
                "--start-year", str(start_year), "--start-week", str(start_week),
                *(("--invalid-subtype", benchmark_invalid_subtype) if benchmark_invalid_subtype else ()),
            )
        plan = resolve_input_plan(
            case_source=case_source,
            climate_source=climate_source,
            operational_source=operational_source,
            use_opendengue=use_opendengue,
            use_nasa_power_climate=use_nasa_power_climate,
            skip_data_generation=skip_data_generation,
            benchmark_args=benchmark_args,
        )
    except (SourcePlanError, FormulaRegistryError, EvidenceRegistryError, DeploymentProfileError, ValueError) as exc:
        print(f"[ERROR] {exc}")
        return 2

    _banner("DengueOps AI — Full Analytics Pipeline")

    if export_only:
        steps_to_run = [
            dict(step) for step in ANALYTICS_STEPS if step["id"] == "dashboard_exporter"
        ]
        print("\n  Mode: --export-dashboard-only (dashboard exporter only)")
    elif plan.reuse_existing:
        steps_to_run = [build_input_validation_step()] + [dict(step) for step in ANALYTICS_STEPS]
        print("\n  Mode: --skip-data-generation (reusing all existing inputs)")
    else:
        steps_to_run = (
            build_input_steps(plan)
            + [build_input_validation_step()]
            + [dict(step) for step in ANALYTICS_STEPS]
        )
        print("\n  Input source plan:")
        print(f"    Cases      : {plan.case_source}")
        print(f"    Climate    : {plan.climate_source}")
        print(f"    Operational: {plan.operational_source}")
        if plan.demo_domains:
            print(f"    Demo writes: {', '.join(plan.demo_domains)}")

    for warning in plan.warnings:
        print(f"  [DEPRECATION] {warning}")

    if run_model_comparison:
        comparison_step = {
            "id": "candidate_model_comparison", "script": ANALYTICS_DIR / "model_candidates.py",
            "description": "Phase P1.2A - Comparing fixed candidate models", "skippable": False,
            "expected_files": [CANDIDATE_COMPARISON_PATH],
        }
        position = next(i for i, step in enumerate(steps_to_run) if step["id"] == "forecast_model")
        steps_to_run.insert(position, comparison_step)

    if governance:
        for step in steps_to_run:
            if step["id"] == "validation_backtest":
                step["expected_files"] = [*step["expected_files"], DATA_DIR / "model_explainability.json"]

    for step in steps_to_run:
        if not step.get("internal"):
            step["env"] = {"DENGUEOPS_DEPLOYMENT_GATE": deployment_gate,
                           "DENGUEOPS_MODEL_COMPARISON_STATUS": "generated" if run_model_comparison else "not_run_current_pipeline"}

    total   = len(steps_to_run)
    completed: list[str] = []
    failed:    str | None = None
    timings:   dict[str, float] = {}
    transaction_snapshot = ({path: path.read_bytes() if path.exists() else None for path in P13_TRANSACTION_PATHS}
                            if governance and run_model_comparison and not export_only else {})

    run_start = datetime.now(timezone.utc)

    for idx, step in enumerate(steps_to_run, start=1):
        _step_header(idx, total, step["description"])
        if step.get("internal"):
            t0 = time.perf_counter()
            try:
                manifest = validate_inputs_and_write_manifest(
                    plan,
                    allow_climate_spatial_proxy=allow_climate_spatial_proxy,
                    allow_mixed_epidemiology_inputs=allow_mixed_epidemiology_inputs,
                    acknowledge_synthetic_operational_data=acknowledge_synthetic_operational_data,
                    governance=governance,
                )
                cross = manifest["cross_source_validation"]
                print(
                    f"  Inputs valid: {cross['overlap_weeks']} contiguous overlap weeks; "
                    f"{cross['expected_supervised_rows']} expected supervised rows."
                )
                print(f"  Manifest: {MANIFEST_PATH}")
                success = True
            except InputValidationError as exc:
                print("\n  [INPUT VALIDATION FAILED]")
                for error in exc.errors:
                    print(f"    - {error}")
                success = False
            except Exception as exc:
                print(f"\n  [INPUT VALIDATION ERROR] {exc}")
                success = False
            elapsed = time.perf_counter() - t0
        else:
            success, elapsed = run_step(step, cwd=ROOT)
        timings[step["id"]] = round(elapsed, 2)

        if not success:
            print(f"\n  [FAILED] {step['id']} exited with non-zero code.")
            if "script" in step:
                print(f"           Script: {step['script']}")
            print("  Pipeline halted. Fix the error above and re-run.")
            failed = step["id"]
            break

        # Do not destroy committed selection evidence before current inputs pass.
        # A non-comparison legacy run clears it only after input validation succeeds.
        if (step["id"] == "input_validation" and not run_model_comparison
                and not export_only and CANDIDATE_COMPARISON_PATH.exists()):
            CANDIDATE_COMPARISON_PATH.unlink()

        # Validate expected outputs
        errors = _validate_step_outputs(step)
        if errors:
            print(f"\n  [FAILED] Output validation after '{step['id']}':")
            for e in errors:
                print(f"    - {e}")
            failed = step["id"]
            break

        print(f"\n  [OK] {step['id']}  ({elapsed:.1f}s)")
        completed.append(step["id"])

    # ── Save run summary ──────────────────────────────────────────────────────
    status = "success" if failed is None else f"failed_at_{failed}"
    _save_run_summary(run_start, status, completed, timings, deployment_gate)

    # ── Final summary ─────────────────────────────────────────────────────────
    if failed is not None:
        if transaction_snapshot:
            _restore_transaction(transaction_snapshot)
            print("  Previous committed P1.3 bundle restored after pipeline failure.")
        return 1

    if transaction_snapshot:
        # Replacing identical validated bytes makes the model card the final publication event.
        card_path = DATA_DIR / "model_card.json"
        card_bytes = card_path.read_bytes()
        card = json.loads(card_bytes)
        uncertainty_bytes = (DATA_DIR / "forecast_uncertainty.json").read_bytes()
        forecast_bytes = (DATA_DIR / "forecast_output.json").read_bytes()
        validate_committed_bundle(json.loads(forecast_bytes), json.loads(uncertainty_bytes), card,
                                  uncertainty_bytes, forecast_bytes)
        _replace_exact(card_path, card_bytes)

    _print_final_summary()
    return 0


# ── Final summary printer ─────────────────────────────────────────────────────

def _print_final_summary() -> None:
    forecast   = _load_json_safe(DATA_DIR / "forecast_output.json")
    directives = _load_json_safe(DATA_DIR / "directives.json")
    rolling = _load_json_safe(DATA_DIR / "rolling_validation.json")
    validation = _load_json_safe(DATA_DIR / "validation_metrics.json")

    if not forecast or not directives or not validation:
        print("\n  [WARNING] Could not load output files for final summary.")
        return

    sc = forecast.get("preparedness_scenarios", {})
    best_c    = sc.get("best_case",     {}).get("forecast_cases", "?")
    exp_c     = sc.get("expected_case", {}).get("forecast_cases", "?")
    worst_c   = sc.get("worst_case",    {}).get("forecast_cases", "?")

    s = directives.get("summary", {})
    comparison = _load_json_safe(DATA_DIR / "candidate_model_comparison.json") or {}
    m = comparison.get("aggregate_metrics", {}).get("random_forest", {})

    total_w = 66
    print()
    print("=" * total_w)
    print("  DengueOps AI Pipeline Complete")
    print("=" * total_w)
    print(f"  Forecast       : {forecast.get('forecast_cases')} cases"
          f"  |  Growth: {forecast.get('forecast_growth_category')} "
          f"(experimental score {forecast.get('experimental_growth_score')})")
    print(f"  Planning L/B/H : {best_c} / {exp_c} / {worst_c} cases")
    print(f"  Active model   : RandomForestRegressor (adopted P1.2B)"
          f"  |  RMSE: {round(float(m.get('rmse', 0)), 1)}"
          f"  |  MAE: {round(float(m.get('mae', 0)), 1)}")
    print(f"  Priority zone  : {s.get('highest_priority_zone', 'N/A')}")
    print(f"  Pressure fac.  : {str(s.get('highest_pressure_facility', 'N/A'))[:50]}")
    print(f"  Critical alerts: {s.get('critical_supply_alerts', 0)}"
          f"  |  Bed gaps: {s.get('facilities_with_expected_bed_gap', 0)} facilities")
    print(f"  Facilities     : {s.get('total_facilities', 0)}"
          f"  ({s.get('total_public_government_anchors', 0)} public/govt anchors)")
    print()
    print("  Dashboard files ready:")
    for fname in ["dashboard_summary.json", "model_comparison.json", "chart_data.json"]:
        print(f"    - data/{fname}")
    print("  Run log:")
    print(f"    - data/pipeline_run_summary.json")
    print("=" * total_w)
    print()


# ── Run summary serializer ────────────────────────────────────────────────────

def _save_run_summary(
    run_start: datetime,
    status: str,
    completed: list[str],
    timings: dict[str, float],
    deployment_gate: str = "benchmark_only",
) -> None:
    """Save a structured pipeline run log to data/pipeline_run_summary.json."""
    forecast   = _load_json_safe(DATA_DIR / "forecast_output.json")
    directives = _load_json_safe(DATA_DIR / "directives.json")
    rolling = _load_json_safe(DATA_DIR / "rolling_validation.json")

    forecast_summary: dict[str, Any] = {}
    if forecast:
        sc = forecast.get("preparedness_scenarios", {})
        forecast_summary = {
            "forecast_cases":  forecast.get("forecast_cases"),
            "growth_factor":   forecast.get("growth_factor"),
            "risk_level":      forecast.get("risk_level"),
            "risk_score":      forecast.get("risk_score"),
            "experimental_growth_score": forecast.get("experimental_growth_score"),
            "forecast_growth_category": forecast.get("forecast_growth_category"),
            "target_epi_week": forecast.get("target_epi_week"),
            "target_epi_year": forecast.get("target_epi_year"),
            "best_case":       sc.get("best_case",     {}).get("forecast_cases"),
            "expected_case":   sc.get("expected_case", {}).get("forecast_cases"),
            "worst_case":      sc.get("worst_case",    {}).get("forecast_cases"),
        }

    directives_summary: dict[str, Any] = {}
    if directives:
        directives_summary = directives.get("summary", {})

    generated_files = [str(f) for f in ALL_OUTPUT_FILES if f.exists()]

    dashboard_outputs: dict[str, Any] = {}
    for name in ("dashboard_summary.json", "model_comparison.json", "chart_data.json", "model_card.json", "model_explainability.json", "candidate_model_comparison.json"):
        p = DATA_DIR / name
        dashboard_outputs[name] = {
            "exists": p.exists(),
            "size_bytes": p.stat().st_size if p.exists() else 0,
        }

    # A producer may intentionally publish an invalid benchmark bundle so the
    # validation gate can reject it. Never read a stale prior manifest on a
    # failed run, because its input hashes correctly no longer match.
    provenance = load_compact_provenance(MANIFEST_PATH) if status == "success" and MANIFEST_PATH.exists() else None
    if status == "success":
        artifact_values = [
            _load_json_safe(DATA_DIR / "validation_metrics.json"), rolling, forecast, directives,
            _load_json_safe(DATA_DIR / "dashboard_summary.json"),
            _load_json_safe(DATA_DIR / "model_comparison.json"),
            _load_json_safe(DATA_DIR / "chart_data.json"),
        ]
        if provenance and provenance.get("deployment_profile_id"):
            artifact_values.append(_load_json_safe(DATA_DIR / "model_card.json"))
            artifact_values.append(_load_json_safe(DATA_DIR / "model_explainability.json"))
            if CANDIDATE_COMPARISON_PATH.exists(): artifact_values.append(_load_json_safe(CANDIDATE_COMPARISON_PATH))
        artifacts = [value for value in artifact_values if value]
        assert_same_provenance(
            provenance, *(artifact_provenance(value, "completed artifact") for value in artifacts)
        )
    data_mode = derive_data_mode(provenance) if provenance else "unknown"
    summary = {
        "provenance": provenance,
        "run_timestamp":       run_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "status":              status,
        "completed_steps":     completed,
        "step_timings_sec":    timings,
        "generated_files":     generated_files,
        "forecast_summary":    forecast_summary,
        "directives_summary":  directives_summary,
        "rolling_validation": {"status": (rolling or {}).get("availability_status", "not_generated"),
                               "fold_count": (rolling or {}).get("fold_count", 0),
                               "primary_validation": (rolling or {}).get("primary_validation", False)},
        "dashboard_outputs":   dashboard_outputs,
        "formula_registry_version": (forecast or {}).get("formula_registry_version"),
        "formula_registry_sha256": (forecast or {}).get("formula_registry_sha256"),
        "formula_ids_used": (directives or forecast or {}).get("formula_ids_used", []),
        "deployment_gate": deployment_gate,
        "formula_validation_status": (directives or forecast or {}).get("formula_validation_status", "not_completed"),
        "notes": [
            "Python pipeline generates dashboard-ready JSON outputs.",
            "Evaluators do not need to inspect terminal outputs.",
            "The Next.js dashboard visualises forecasts, validation metrics, "
            "uncertainty, SDH, bed gaps, and zone/facility directives.",
            "All readiness and inventory values are synthetic demonstration data.",
            "Facility identity and readiness status are source-specific; benchmark facilities are wholly synthetic.",
            f"Input data mode: {data_mode}; exact sources are recorded in provenance.",
        ],
    }
    model_card = _load_json_safe(DATA_DIR / "model_card.json") if provenance and provenance.get("deployment_profile_id") else None
    if model_card:
        statements = model_card["maturity_statements"]
        summary["deployment_profile"] = {
            "profile_id": model_card["deployment_id"],
            "profile_status": provenance["deployment_profile_status"],
            "demonstration_status": model_card["data_mode"],
            "maturity_statement": statements["maturity"],
            "demonstration_statement": statements["demonstration"],
            "prohibited_claim": statements["prohibited_claim"],
            "notification_wording": statements["notification"],
            "deployment_gate": model_card["deployment_gate"],
            "evidence_status": "empty_registry" if not model_card["evidence_ids"] else "linked_evidence",
            "approval_status": model_card["approval_status"],
        }
        explainability = _load_json_safe(DATA_DIR / "model_explainability.json")
        summary["explainability"] = {
            "status": model_card["explainability_status"],
            "artifact_path": model_card["explainability_artifact_path"],
            "artifact_sha256": model_card["explainability_artifact_sha256"],
            "methods": model_card["explainability_methods"],
            "estimator_role": model_card["explainability_evaluation"]["estimator_role"],
            "stability_status": model_card["importance_stability_status"],
            "feature_count": len(explainability.get("feature_names", [])) if explainability else 0,
        }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n  Run log saved: {RUN_SUMMARY_PATH}")


# ── CLI entry point ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description="DengueOps AI — Full Analytics Pipeline Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analytics/run_pipeline.py
      Run the full pipeline with controlled synthetic Dhaka South demo data.
      This is the default demonstration mode.

  python analytics/run_pipeline.py --skip-data-generation
      Skip data generation. Use existing input CSV/JSON files.

  python analytics/run_pipeline.py --validate-only
      Check whether all output files exist and are well-formed.

  python analytics/run_pipeline.py --export-dashboard-only
      Run only the dashboard exporter (Step 7).

  [Experimental real-data pathways — not the default demo]
  python analytics/run_pipeline.py --use-opendengue
      Replace synthetic dengue_cases.csv with OpenDengue Bangladesh national data.

  python analytics/run_pipeline.py --use-nasa-power-climate
      Replace synthetic climate_data.csv with NASA POWER data.

  python analytics/run_pipeline.py --use-opendengue --use-nasa-power-climate
      Use both real data sources (experimental validation pathway).
        """,
    )
    parser.add_argument(
        "--skip-data-generation",
        action="store_true",
        help="Skip all case, climate, and operational producers; reuse existing inputs.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only check output file existence and validity. No steps are run.",
    )
    parser.add_argument(
        "--export-dashboard-only",
        action="store_true",
        help="Only run dashboard_exporter.py (Step 7).",
    )
    parser.add_argument(
        "--case-source",
        choices=CASE_SOURCES,
        default=None,
        help="Producer for dengue case inputs (default: synthetic_demo).",
    )
    parser.add_argument(
        "--climate-source",
        choices=CLIMATE_SOURCES,
        default=None,
        help="Producer for climate inputs (default: synthetic_demo).",
    )
    parser.add_argument(
        "--operational-source",
        choices=OPERATIONAL_SOURCES,
        default=None,
        help="Producer for operational inputs (default: synthetic_demo).",
    )
    parser.add_argument(
        "--allow-climate-spatial-proxy",
        action="store_true",
        help="Acknowledge an explicitly associated point climate source as a city proxy.",
    )
    parser.add_argument(
        "--allow-mixed-epidemiology-inputs",
        action="store_true",
        help="Acknowledge mixing synthetic and real case/climate inputs.",
    )
    parser.add_argument(
        "--acknowledge-synthetic-operational-data",
        action="store_true",
        help="Acknowledge synthetic operations when both epidemiology inputs are real.",
    )
    parser.add_argument(
        "--use-nasa-power-climate",
        action="store_true",
        help=(
            "[Experimental] Fetch NASA POWER climate data for Dhaka South and use it as "
            "climate_data.csv (replaces synthetic climate). Uses cached raw file if available."
        ),
    )
    parser.add_argument(
        "--use-opendengue",
        action="store_true",
        help=(
            "[Experimental] Fetch real Bangladesh national dengue data from OpenDengue V1.3 "
            "(Clarke et al. 2024) and use it as dengue_cases.csv (replaces synthetic cases). "
            "Note: real data covers 2014–2024 (national level). The default synthetic dataset "
            "is better suited for the preparedness workflow demonstration."
        ),
    )

    parser.add_argument("--benchmark-scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--benchmark-seed", type=int, default=42)
    parser.add_argument("--benchmark-weeks", type=int, default=180)
    parser.add_argument("--benchmark-start-year", type=int, default=2021)
    parser.add_argument("--benchmark-start-week", type=int, default=1)
    parser.add_argument("--benchmark-invalid-subtype", choices=INVALID_SUBTYPES)
    parser.add_argument("--deployment-gate", choices=DEPLOYMENT_GATES, default="benchmark_only")
    parser.add_argument("--deployment-profile", default=None, help="Validated deployment profile ID under config/deployments/.")
    parser.add_argument("--run-model-comparison", action="store_true", help="Generate current-run P1.2A candidate comparison evidence.")

    args = parser.parse_args()
    benchmark_option_names = {
        "--benchmark-scenario", "--benchmark-seed", "--benchmark-weeks",
        "--benchmark-start-year", "--benchmark-start-week", "--benchmark-invalid-subtype",
    }
    benchmark_options_explicit = any(
        token.split("=", 1)[0] in benchmark_option_names for token in sys.argv[1:]
    )
    deployment_gate_explicit = any(
        token.split("=", 1)[0] == "--deployment-gate" for token in sys.argv[1:]
    )
    selected_gate = args.deployment_gate if deployment_gate_explicit else None

    if args.validate_only:
        sys.exit(cmd_validate_only())
    elif args.export_dashboard_only:
        sys.exit(run_pipeline(
            export_only=True,
            skip_data_generation=args.skip_data_generation,
            case_source=args.case_source,
            climate_source=args.climate_source,
            operational_source=args.operational_source,
            use_nasa_power_climate=args.use_nasa_power_climate,
            use_opendengue=args.use_opendengue,
            allow_climate_spatial_proxy=args.allow_climate_spatial_proxy,
            allow_mixed_epidemiology_inputs=args.allow_mixed_epidemiology_inputs,
            acknowledge_synthetic_operational_data=args.acknowledge_synthetic_operational_data,
            benchmark_scenario=args.benchmark_scenario, benchmark_seed=args.benchmark_seed,
            benchmark_weeks=args.benchmark_weeks, benchmark_start_year=args.benchmark_start_year,
            benchmark_start_week=args.benchmark_start_week, benchmark_invalid_subtype=args.benchmark_invalid_subtype,
            benchmark_options_explicit=benchmark_options_explicit,
            deployment_gate=selected_gate,
            deployment_profile=args.deployment_profile,
            run_model_comparison=args.run_model_comparison,
        ))
    else:
        sys.exit(run_pipeline(
            skip_data_generation=args.skip_data_generation,
            case_source=args.case_source,
            climate_source=args.climate_source,
            operational_source=args.operational_source,
            use_nasa_power_climate=args.use_nasa_power_climate,
            use_opendengue=args.use_opendengue,
            allow_climate_spatial_proxy=args.allow_climate_spatial_proxy,
            allow_mixed_epidemiology_inputs=args.allow_mixed_epidemiology_inputs,
            acknowledge_synthetic_operational_data=args.acknowledge_synthetic_operational_data,
            benchmark_scenario=args.benchmark_scenario, benchmark_seed=args.benchmark_seed,
            benchmark_weeks=args.benchmark_weeks, benchmark_start_year=args.benchmark_start_year,
            benchmark_start_week=args.benchmark_start_week, benchmark_invalid_subtype=args.benchmark_invalid_subtype,
            benchmark_options_explicit=benchmark_options_explicit,
            deployment_gate=selected_gate,
            deployment_profile=args.deployment_profile,
            run_model_comparison=args.run_model_comparison,
        ))


if __name__ == "__main__":
    main()
