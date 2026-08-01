from __future__ import annotations

import hashlib
import json
import sys
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from formula_policy import load_formula_activation_policy, resolve_active_formula  # noqa: E402
from formula_registry import load_governed_formula_registry  # noqa: E402
from runtime_operational_preparedness import build_artifacts  # noqa: E402
from safe_formula import evaluate_formula_canonical  # noqa: E402


def canonical_sha(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def authority(expression: str) -> dict:
    formula = {
        "formulaId": "inventory.gap.test",
        "formulaVersion": "1.0.0",
        "formulaSha256": "a" * 64,
        "formulaSlot": "inventory.gap",
        "expression": expression,
        "inputs": [{"name": name} for name in ("allocatedForecastCases", "resourcePerCase", "availableResource")],
        "outputUnit": "bed_units",
    }
    snapshot = {"forecastRunId": "11111111-1111-4111-8111-111111111111", "formulaSha256": formula["formulaSha256"]}
    return {
        "forecast": {"forecast": {"forecastReported": 144, "targetPeriod": "2026-W32"}},
        "formula": formula,
        "formulaPolicy": {"authorityGate": {"resourcePerCase": "0.050000"}},
        "inventory": {"inventory": {"hospitals": [
            {"hospitalId": "known", "officialName": "Known Hospital", "active": True, "participationStatus": "included", "selectedBedCapacity": 10},
            {"hospitalId": "unknown", "officialName": "Unknown Hospital", "active": True, "participationStatus": "included", "selectedBedCapacity": None},
        ]}},
        "snapshot": snapshot,
        "authoritySnapshotSha256": canonical_sha(snapshot),
    }


def test_initial_operational_formula_is_exact_parity_and_qualification_identity_is_preserved() -> None:
    registry = load_governed_formula_registry()
    qualification, operational = registry["formulas"]
    policy = load_formula_activation_policy()
    assert qualification["formulaId"] == "inventory.gap.synthetic-qualification.v1"
    assert qualification["formulaSha256"] == "ee446cacbff6ee82b065b01cce1b33aea1d8df214955852639acf998cc7b58c1"
    assert qualification["expression"] == operational["expression"]
    assert qualification["inputs"] == operational["inputs"]
    assert qualification["outputUnit"] == operational["outputUnit"]
    assert resolve_active_formula("inventory.gap", policy=policy, registry=registry) == operational
    values = {"allocatedForecastCases": 144, "resourcePerCase": "0.050000", "availableResource": 5}
    assert evaluate_formula_canonical(qualification["expression"], values) == evaluate_formula_canonical(operational["expression"], values)


def test_formula_drives_dynamic_numbers_without_forecast_or_inventory_change() -> None:
    fixed_id = str(uuid.uuid4())
    before, before_rows = build_artifacts(authority("max(0, ceil(allocatedForecastCases * resourcePerCase) - availableResource)"), fixed_id, "2026-08-01T00:00:00Z")
    after, after_rows = build_artifacts(authority("ceil(allocatedForecastCases * resourcePerCase)"), str(uuid.uuid4()), "2026-08-01T00:00:01Z")
    first_before, unknown_before = before_rows["rows"]
    first_after, unknown_after = after_rows["rows"]
    assert before["forecast"] == after["forecast"]
    assert first_before["preparednessMetric"]["value"] == 0
    assert first_after["preparednessMetric"]["value"] == 8
    assert unknown_before["preparednessMetric"]["status"] == "unavailable_missing_input"
    assert unknown_after["preparednessMetric"]["value"] is None
    assert all(row["currentLiveAvailability"] == {"value": None, "status": "not_reported"} for row in after_rows["rows"])


def test_generator_contains_no_hardcoded_formula_expression() -> None:
    source = (ROOT / "analytics" / "runtime_operational_preparedness.py").read_text(encoding="utf-8")
    expression = "max(0, ceil(allocatedForecastCases * resourcePerCase) - availableResource)"
    assert expression not in source
    assert "evaluate_formula_canonical(expression" in source
    assert "eval(" not in source and "exec(" not in source


def test_operational_artifacts_and_job_satisfy_strict_schemas() -> None:
    preparedness_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    summary, facilities = build_artifacts(authority("max(0, ceil(allocatedForecastCases * resourcePerCase) - availableResource)"), preparedness_id, "2026-08-01T00:00:00Z")
    for value, name in ((summary, "runtime_operational_preparedness.schema.json"), (facilities, "runtime_operational_facility_preparedness.schema.json")):
        schema = json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    job = {"schemaVersion":"1.0","jobKind":"operational_preparedness","jobId":job_id,"preparednessId":preparedness_id,"deploymentId":"dhaka_south","workflowMode":"operational_preparedness","authoritySnapshotSha256":"a"*64,"status":"queued","progress":"waiting_for_preparedness_worker","createdAt":"2026-08-01T00:00:00Z","claimedAt":None,"startedAt":None,"updatedAt":"2026-08-01T00:00:00Z","completedAt":None,"heartbeatAt":None,"workerId":None,"processId":None,"timeoutSeconds":300,"retryCount":0,"error":None,"committedPreparednessId":None}
    schema = json.loads((ROOT / "config" / "runtime_job.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(job)


@pytest.mark.parametrize("field", ["formulaSha256", "inventoryPointerSha256", "planningPolicySha256", "forecastPointerSha256"])
def test_authority_snapshot_changes_when_any_downstream_authority_changes(field: str) -> None:
    snapshot = {"formulaSha256": "a" * 64, "inventoryPointerSha256": "b" * 64, "planningPolicySha256": "c" * 64, "forecastPointerSha256": "d" * 64}
    before = canonical_sha(snapshot)
    snapshot[field] = "e" * 64
    assert canonical_sha(snapshot) != before
