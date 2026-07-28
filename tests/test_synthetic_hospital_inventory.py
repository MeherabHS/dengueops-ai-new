from __future__ import annotations

import copy
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from hospital_capacity_reference import load_capacity_reference  # noqa: E402
from synthetic_hospital_inventory import (  # noqa: E402
    generate_synthetic_inventory,
    load_scenario_policy,
    load_synthetic_inventory,
)


def test_generation_is_deterministic_and_does_not_mutate_official_capacity() -> None:
    capacity = load_capacity_reference()
    before = json.dumps(capacity, sort_keys=True)
    first = generate_synthetic_inventory(capacity, load_scenario_policy())
    second = generate_synthetic_inventory(copy.deepcopy(capacity), load_scenario_policy())
    assert first == second == load_synthetic_inventory()
    assert json.dumps(capacity, sort_keys=True) == before


def test_three_scenarios_are_labelled_synthetic_and_differ() -> None:
    value = load_synthetic_inventory()
    scenarios = {item["scenarioId"]: item for item in value["scenarios"]}
    assert set(scenarios) == {"baseline_availability", "constrained_availability", "severe_constraint"}
    totals = []
    for scenario in scenarios.values():
        totals.append(sum(row["quantity"] or 0 for row in scenario["hospitals"]))
        assert all(row["synthetic"] is True for row in scenario["hospitals"])
        assert all("dataStatus" not in row for row in scenario["hospitals"])
        assert all(row["resultStatus"] != "verified" for row in scenario["hospitals"])
        shares = [Decimal(row["allocationShare"]) for row in scenario["hospitals"] if row["allocationStatus"] == "configured"]
        assert sum(shares, Decimal(0)) == Decimal("1.000000")
    assert totals[0] > totals[1] > totals[2]


def test_unknown_capacity_and_noneligible_rows_never_receive_allocation() -> None:
    value = load_synthetic_inventory()
    for scenario in value["scenarios"]:
        for row in scenario["hospitals"]:
            if row["officialCapacityReference"]["quantity"] is None or row["eligibility"] not in {"eligible", "potentially_eligible"}:
                assert row["allocationShare"] is None
                assert row["quantity"] is None
