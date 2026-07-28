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
    canonical_sha256,
    generate_synthetic_inventory,
    load_scenario_policy,
    load_synthetic_inventory,
    validate_scenario_policy,
    validate_synthetic_inventory,
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


def test_management_cohort_capacity_controls_allocation() -> None:
    value = load_synthetic_inventory()
    policy = load_scenario_policy()
    for scenario in value["scenarios"]:
        assert [row["hospitalId"] for row in scenario["hospitals"]] == policy["participatingHospitalIds"]
        for row in scenario["hospitals"]:
            assert row["participationStatus"] == "included"
            assert row["managementDecisionStatus"] == "pending_review"
            if row["officialCapacityReference"]["quantity"] is None:
                assert row["allocationShare"] is None
                assert row["quantity"] is None
                assert row["resultStatus"] == "insufficient_capacity_reference"
            else:
                assert row["allocationStatus"] == "configured"
                assert row["allocationShare"] is not None


def test_historical_v1_synthetic_contract_remains_verifiable() -> None:
    policy = copy.deepcopy(load_scenario_policy())
    policy["policyVersion"] = "b8.5-v1"
    policy.pop("participatingHospitalIds")
    policy.pop("participationDecisionStatus")
    policy["policySha256"] = canonical_sha256(policy, frozenset({"policySha256"}))
    validate_scenario_policy(policy)
    legacy = generate_synthetic_inventory(load_capacity_reference(), policy)
    assert legacy["syntheticInventoryVersion"] == "1.0.0"
    assert all("participationStatus" not in row for row in legacy["scenarios"][0]["hospitals"])
    validate_synthetic_inventory(legacy, reference=load_capacity_reference(), policy=policy)
