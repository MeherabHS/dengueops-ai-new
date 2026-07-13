"""Frozen configuration and calendar utilities for benchmark-v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

SIMULATION_VERSION = "benchmark-v1"
CONFIG_VERSION = "1.0"


@dataclass(frozen=True)
class BenchmarkConfig:
    simulation_version: str = SIMULATION_VERSION
    config_version: str = CONFIG_VERSION
    seed: int = 42
    scenario: str = "normal"
    invalid_subtype: str | None = None
    start_year: int = 2021
    start_week: int = 1
    number_of_weeks: int = 180
    geography_level: str = "city"
    geography_id: str = "BGD-DHAKA-SOUTH"
    geography_name: str = "Dhaka South"
    latitude: float = 23.7104
    longitude: float = 90.4074
    climate_strength: float = 0.42
    autoregressive_strength: float = 0.36
    death_rate: float = 0.003
    observation_dispersion: float = 18.0
    climate_shock_magnitude: float = 0.0
    transmission_shock_magnitude: float = 0.0
    current_reporting_fraction: float = 0.62
    delayed_fraction: float = 0.38
    reporting_delay_weeks: int = 2
    facility_pressure_fraction: float = 0.0
    stock_stress_fraction: float = 0.0
    replenishment_fraction: float = 0.0
    replenishment_week: int = 150
    min_temperature_c: float = 15.0
    max_temperature_c: float = 40.0
    min_humidity_pct: float = 35.0
    max_humidity_pct: float = 100.0

    def as_dict(self) -> dict:
        return asdict(self)


def validate_config(config: BenchmarkConfig) -> BenchmarkConfig:
    from .scenarios import INVALID_SUBTYPES, SCENARIOS

    errors: list[str] = []
    if config.simulation_version != SIMULATION_VERSION:
        errors.append(f"simulation_version must be {SIMULATION_VERSION}.")
    if config.config_version != CONFIG_VERSION:
        errors.append(f"config_version must be {CONFIG_VERSION}.")
    if not isinstance(config.seed, int) or isinstance(config.seed, bool) or config.seed < 0:
        errors.append("seed must be a nonnegative integer.")
    if config.scenario not in SCENARIOS:
        errors.append(f"Unknown scenario '{config.scenario}'.")
    if config.invalid_subtype is not None and config.invalid_subtype not in INVALID_SUBTYPES:
        errors.append(f"Unknown invalid subtype '{config.invalid_subtype}'.")
    if config.scenario == "messy_invalid" and config.invalid_subtype is None:
        errors.append("messy_invalid requires one explicit invalid subtype.")
    if config.scenario != "messy_invalid" and config.invalid_subtype is not None:
        errors.append("An invalid subtype is only valid with messy_invalid.")
    if config.number_of_weeks < 104:
        errors.append("number_of_weeks must be at least 104.")
    if config.start_year < 1900 or config.start_year > 2100 or not 1 <= config.start_week <= 52:
        errors.append("start_year/start_week must identify a supported W01-W52 period.")
    if (config.geography_level, config.geography_id, config.geography_name) != ("city", "BGD-DHAKA-SOUTH", "Dhaka South"):
        errors.append("Only city/BGD-DHAKA-SOUTH/Dhaka South geography is supported.")
    if not (-90 <= config.latitude <= 90 and -180 <= config.longitude <= 180):
        errors.append("latitude/longitude are out of range.")
    for name in ("death_rate", "current_reporting_fraction", "delayed_fraction", "facility_pressure_fraction", "stock_stress_fraction", "replenishment_fraction"):
        if not 0 <= getattr(config, name) <= 1:
            errors.append(f"{name} must be within 0 and 1.")
    if abs(config.current_reporting_fraction + config.delayed_fraction - 1.0) > 1e-9:
        errors.append("Reporting fractions must sum to 1.")
    for name in ("climate_strength", "autoregressive_strength", "observation_dispersion"):
        if getattr(config, name) <= 0:
            errors.append(f"{name} must be positive.")
    for name in ("climate_shock_magnitude", "transmission_shock_magnitude"):
        if getattr(config, name) < 0:
            errors.append(f"{name} must be nonnegative.")
    if not (15 <= config.min_temperature_c < config.max_temperature_c <= 40):
        errors.append("Climate temperature bounds must be within 15..40.")
    if not (35 <= config.min_humidity_pct < config.max_humidity_pct <= 100):
        errors.append("Climate humidity bounds must be within 35..100.")
    if config.reporting_delay_weeks < 1:
        errors.append("reporting_delay_weeks must be positive.")
    if not 0 <= config.replenishment_week < config.number_of_weeks:
        errors.append("replenishment_week must fall inside the generated period.")
    if errors:
        raise ValueError(" ".join(errors))
    periods_from_config(config)
    return config


def periods_from_config(config: BenchmarkConfig) -> tuple[tuple[int, int, str], ...]:
    """Return stable W01-W52 periods with ISO Monday dates and no W53."""
    ordinal = config.start_year * 52 + config.start_week - 1
    periods = []
    for offset in range(config.number_of_weeks):
        value = ordinal + offset
        year, week0 = divmod(value, 52)
        week = week0 + 1
        periods.append((year, week, date.fromisocalendar(year, week, 1).isoformat()))
    return tuple(periods)
