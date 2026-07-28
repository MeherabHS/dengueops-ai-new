from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

import runtime_hospital_preparedness as preparedness_module  # noqa: E402
import runtime_hospital_preparedness_commit as commit_module  # noqa: E402
import runtime_hospital_preparedness_verify as verify_module  # noqa: E402
from runtime_hospital_preparedness import build_preparedness_evidence  # noqa: E402
from runtime_hospital_preparedness_commit import publish_qualification  # noqa: E402
from runtime_hospital_preparedness_verify import (  # noqa: E402
    HospitalPreparednessVerificationError,
    list_qualifications,
    verify_qualification,
)


def source_fixture() -> dict:
    run_id = str(uuid.uuid4())
    commit_sha = "a" * 64
    bundle = {
        "sourceFamily": "quick_forecast_p2",
        "commit": {"schemaVersion": "2.1", "runId": run_id, "workflowMode": "quick_forecast"},
        "forecast": {
            "runId": run_id,
            "forecastReported": 1000,
            "target": "target_cases_next_2w",
            "targetPeriod": "2026-W32",
            "horizonWeeks": 2,
            "forecastPresentationMode": "point_only",
            "calibrationStatus": "unavailable",
        },
        "uncertainty": {"forecastPresentationMode": "point_only", "calibrationStatus": "unavailable"},
        "modelId": "fixture-model",
        "modelFamily": "FixtureModel",
        "parameterHash": "b" * 64,
        "sourcePolicy": {"policyId": "fixture-policy", "policyVersion": "1", "policySha256": "c" * 64},
        "assignment": {"assignmentId": str(uuid.uuid4())},
    }
    return {
        "pointer": {"runId": run_id},
        "pointerSha256": "d" * 64,
        "runId": run_id,
        "commitSha256": commit_sha,
        "commitPath": Path("unused"),
        "bundle": bundle,
    }


@pytest.fixture
def governed_source(monkeypatch: pytest.MonkeyPatch) -> dict:
    source = source_fixture()
    monkeypatch.setattr(commit_module, "resolve_current_quick_forecast", lambda _root: source)
    monkeypatch.setattr(
        verify_module,
        "verify_forecast_source",
        lambda _root, run_id, commit_sha, _families: source["bundle"]
        if (run_id, commit_sha) == (source["runId"], source["commitSha256"])
        else (_ for _ in ()).throw(ValueError("source mismatch")),
    )
    return source


def test_three_scenarios_publish_immutable_packages_and_only_qualification_pointer(
    tmp_path: Path, governed_source: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = tmp_path.resolve()
    model_pointer = runtime / "deployments/dhaka_south/model-assignment/latest.json"
    model_pointer.parent.mkdir(parents=True)
    model_pointer.write_text('{"unchanged":true}\\n', encoding="utf-8")
    model_before = model_pointer.read_bytes()
    ids = []
    for scenario in ("baseline_availability", "constrained_availability", "severe_constraint"):
        result = publish_qualification(runtime, scenario)
        ids.append(result["preparednessId"])
        verified = verify_qualification(runtime, result["preparednessId"])
        assert verified["evidence"]["evidenceScope"] == "synthetic_qualification"
        assert verified["evidence"]["operationalUseAllowed"] is False
        statuses = {row["status"] for row in verified["evidence"]["hospitals"]}
        assert "insufficient_capacity_reference" in statuses
        assert statuses <= {
            "calculated_synthetic_gap_present",
            "no_calculated_synthetic_gap",
            "insufficient_capacity_reference",
        }
    assert list_qualifications(runtime) == sorted(ids)
    assert model_pointer.read_bytes() == model_before
    assert not (runtime / "deployments/dhaka_south/hospital-preparedness/latest.json").exists()
    assert (runtime / "deployments/dhaka_south/hospital-preparedness-qualification/latest.json").is_file()
    scenario = {
        "scenarioId": "focused_gap_paths",
        "hospitals": [
            {
                "hospitalId": "positive-gap",
                "allocationStatus": "configured",
                "allocationShare": "0.500000",
                "quantity": 0,
            },
            {
                "hospitalId": "zero-gap",
                "allocationStatus": "configured",
                "allocationShare": "0.500000",
                "quantity": 1000,
            },
        ],
    }
    monkeypatch.setattr(
        preparedness_module,
        "load_synthetic_inventory",
        lambda: {
            "syntheticInventoryId": "focused-inventory",
            "syntheticInventorySha256": "e" * 64,
            "scenarios": [scenario],
        },
    )
    monkeypatch.setattr(
        preparedness_module,
        "load_scenario_policy",
        lambda: {
            "policyId": "focused-policy",
            "policySha256": "f" * 64,
            "coefficient": {"resourcePerCase": "1.000000"},
        },
    )
    evidence = build_preparedness_evidence(
        source_fixture(), "focused_gap_paths", str(uuid.uuid4()), "2026-07-28T00:00:00Z"
    )
    results = {row["hospitalId"]: row for row in evidence["hospitals"]}
    assert results["positive-gap"]["status"] == "calculated_synthetic_gap_present"
    assert results["positive-gap"]["syntheticGap"] == "500"
    assert results["zero-gap"]["status"] == "no_calculated_synthetic_gap"
    assert results["zero-gap"]["syntheticGap"] == "0"


def test_previous_evidence_remains_readable_and_tampering_fails(
    tmp_path: Path, governed_source: dict
) -> None:
    runtime = tmp_path.resolve()
    first = publish_qualification(runtime, "baseline_availability")
    second = publish_qualification(runtime, "constrained_availability")
    assert verify_qualification(runtime, first["preparednessId"])["evidence"]["scenarioId"] == "baseline_availability"
    assert verify_qualification(runtime, second["preparednessId"])["evidence"]["scenarioId"] == "constrained_availability"
    artifact = runtime / "hospital-preparedness-qualification" / first["preparednessId"] / "artifacts/preparedness_evidence.json"
    value = json.loads(artifact.read_text(encoding="utf-8"))
    value["operationalUseAllowed"] = True
    artifact.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(HospitalPreparednessVerificationError):
        verify_qualification(runtime, first["preparednessId"])


def test_failed_generation_leaves_qualification_pointer_unchanged(
    tmp_path: Path, governed_source: dict
) -> None:
    runtime = tmp_path.resolve()
    publish_qualification(runtime, "baseline_availability")
    pointer = runtime / "deployments/dhaka_south/hospital-preparedness-qualification/latest.json"
    before = pointer.read_bytes()
    with pytest.raises(ValueError):
        publish_qualification(runtime, "unsupported_scenario")
    assert pointer.read_bytes() == before
