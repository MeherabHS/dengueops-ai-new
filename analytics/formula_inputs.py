"""Trusted variable catalogs for supported governed formula slots."""
from __future__ import annotations

from typing import Any, Mapping

INVENTORY_GAP_SLOT = "inventory.gap"
SUPPORTED_FORMULA_SLOTS = frozenset({INVENTORY_GAP_SLOT})
VARIABLE_CATALOG: dict[str, tuple[dict[str, str], ...]] = {
    INVENTORY_GAP_SLOT: (
        {"name": "allocatedForecastCases", "unit": "cases_per_two_week_forecast_horizon", "domain": "nonnegative_decimal"},
        {"name": "resourcePerCase", "unit": "bed_units_per_case_per_two_week_forecast_horizon", "domain": "nonnegative_decimal"},
        {"name": "availableResource", "unit": "bed_units", "domain": "nonnegative_integer"},
    ),
}


class FormulaInputError(ValueError):
    """Raised when a registry entry differs from its trusted slot catalog."""


def validate_formula_input_catalog(formula: Mapping[str, Any]) -> None:
    slot = formula.get("formulaSlot")
    if slot not in SUPPORTED_FORMULA_SLOTS:
        raise FormulaInputError("Unsupported formula slot.")
    inputs = formula.get("inputs")
    if not isinstance(inputs, list):
        raise FormulaInputError("Formula inputs must be an array.")
    names = [entry.get("name") for entry in inputs if isinstance(entry, dict)]
    if len(names) != len(set(names)):
        raise FormulaInputError("Formula inputs contain duplicate variables.")
    expected = {entry["name"]: entry for entry in VARIABLE_CATALOG[str(slot)]}
    actual = {entry.get("name"): entry for entry in inputs if isinstance(entry, dict)}
    if actual != expected:
        raise FormulaInputError("Formula input catalog does not match trusted slot variables and units.")


def allowed_variable_names(slot: str) -> frozenset[str]:
    if slot not in VARIABLE_CATALOG:
        raise FormulaInputError("Unsupported formula slot.")
    return frozenset(entry["name"] for entry in VARIABLE_CATALOG[slot])
