"""Stable public API for the synthetic benchmark data engine."""

from .config import CONFIG_VERSION, SIMULATION_VERSION, BenchmarkConfig, periods_from_config, validate_config
from .generate_benchmark_data import generate_benchmark, validate_bundle, write_bundle_atomic
from .scenarios import INVALID_SUBTYPES, SCENARIOS, apply_scenario, build_expectations

__all__ = [
    "CONFIG_VERSION", "SIMULATION_VERSION", "BenchmarkConfig", "SCENARIOS",
    "INVALID_SUBTYPES", "apply_scenario", "build_expectations",
    "periods_from_config", "validate_config", "generate_benchmark",
    "validate_bundle", "write_bundle_atomic",
]
