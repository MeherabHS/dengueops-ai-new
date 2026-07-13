"""Scenario presets and qualitative benchmark expectations."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import BenchmarkConfig

SCENARIOS = (
    "normal", "early_surge", "severe_surge", "facility_pressure",
    "stock_stress", "replenishment", "reporting_delay", "messy_invalid",
)
INVALID_SUBTYPES = (
    "missing_week", "duplicate_week", "negative_cases", "invalid_humidity",
    "broken_facility_reference", "occupancy_above_capacity",
)

_PRESETS = {
    "normal": {},
    "early_surge": {"climate_shock_magnitude": 0.48, "transmission_shock_magnitude": 1.05},
    "severe_surge": {"climate_shock_magnitude": 0.48, "transmission_shock_magnitude": 0.95, "facility_pressure_fraction": 0.22, "stock_stress_fraction": 0.18},
    "facility_pressure": {"facility_pressure_fraction": 0.48},
    "stock_stress": {"stock_stress_fraction": 0.58},
    "replenishment": {"replenishment_fraction": 0.55},
    "reporting_delay": {},
    "messy_invalid": {},
}


def apply_scenario(base_config: "BenchmarkConfig", scenario: str) -> "BenchmarkConfig":
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario '{scenario}'.")
    return replace(base_config, scenario=scenario, **_PRESETS[scenario])


def build_expectations(config: "BenchmarkConfig") -> dict:
    direction = {
        "normal": ("seasonal", "baseline", "baseline", "baseline"),
        "early_surge": ("earlier_peak", "higher", "baseline", "baseline"),
        "severe_surge": ("higher", "higher", "higher", "higher"),
        "facility_pressure": ("seasonal", "baseline", "higher", "baseline"),
        "stock_stress": ("seasonal", "baseline", "baseline", "higher"),
        "replenishment": ("seasonal", "baseline", "baseline", "lower"),
        "reporting_delay": ("delayed", "delayed", "baseline", "baseline"),
        "messy_invalid": ("invalid", "not_applicable", "not_applicable", "not_applicable"),
    }[config.scenario]
    return {
        "expected_validation_status": "failed" if config.scenario == "messy_invalid" else "passed",
        "expected_case_direction": direction[0],
        "expected_relative_severity": direction[1],
        "expected_forecast_direction": direction[1],
        "expected_bed_pressure_direction": direction[2],
        "expected_stock_pressure_direction": direction[3],
        "expected_replenishment_behavior": "higher_endpoint_stock" if config.scenario == "replenishment" else "none",
        "comparison_scenario": "normal" if config.scenario != "normal" else None,
        "invalid_data_subtype": config.invalid_subtype,
    }
