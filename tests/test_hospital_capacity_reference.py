from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from dhaka_hospital_research import (  # noqa: E402
    DhakaHospitalResearchError,
    classify_registry_rows,
    load_coverage,
    parse_registry_rows,
)
from hospital_capacity_reference import (  # noqa: E402
    HospitalCapacityReferenceError,
    canonical_sha256,
    load_capacity_reference,
    validate_capacity_reference,
)


def test_official_coverage_accounting_and_completeness_qualification() -> None:
    coverage = load_coverage()
    assert coverage["totalOfficialRecordsReviewed"] == 161
    assert coverage["detailedInpatientCandidatesReviewed"] == 47
    assert len(coverage["includedHospitals"]) == 38
    assert len(coverage["excludedFacilities"]) == 5
    assert len(coverage["unresolvedFacilities"]) == 4
    assert coverage["completenessLimitations"]


def test_registry_parser_filters_active_scope_types_and_duplicate_aliases() -> None:
    html = """
    <table><tr><td>31</td><td>Hospital A</td><td>bn</td><td>10000033</td><td>x</td>
    <td>DGHS</td><td>Medical College Hospital</td><td>Dhaka</td><td>Dhaka</td>
    <td>Dhaka South City Corporation</td><td>Shahbag</td><td></td><td></td><td>0</td></tr></table>
    """
    rows = parse_registry_rows(html)
    assert classify_registry_rows(rows)["inpatientCandidates"][0]["officialFacilityRegistryId"] == 31
    with pytest.raises(DhakaHospitalResearchError, match="Duplicate"):
        classify_registry_rows(rows + rows)


def test_capacity_reference_preserves_approved_latest_conflicts_and_blanks() -> None:
    reference = load_capacity_reference()
    assert reference["capacityReferenceVersion"] == "2.0.0"
    assert len(reference["hospitals"]) == 41
    rows = {item["hospitalId"]: item for item in reference["hospitals"]}
    dmch = rows["dhaka-medical-college-hospital"]
    assert dmch["approvedBedCount"] == 2600
    assert dmch["latestBedCount"] == 0
    assert dmch["latestBedCountStatus"] == "registry_zero_not_accepted_as_operational_zero"
    assert dmch["selectedBedCapacity"]["quantity"] == 2600
    mugda = rows["mugda-medical-college-hospital"]
    assert (mugda["approvedBedCount"], mugda["latestBedCount"]) == (500, 453)
    assert mugda["selectedBedCapacity"]["basis"] == "latest_official_operational_count"
    assert rows["tejgaon-health-complex"]["selectedBedCapacity"]["quantity"] is None
    assert rows["aminbazar-20-bed-government-hospital"]["selectedBedCapacity"]["quantity"] == 20
    assert rows["bangladesh-shishu-hospital-institute"]["selectedBedCapacity"]["quantity"] == 681
    assert rows["dncc-dedicated-specialized-hospital"]["selectedBedCapacity"]["quantity"] == 1054


def test_registry_zero_and_source_tampering_fail_closed() -> None:
    reference = load_capacity_reference()
    tampered = copy.deepcopy(reference)
    row = next(item for item in tampered["hospitals"] if item["latestBedCount"] == 0 and item["approvedBedCount"])
    row["selectedBedCapacity"]["quantity"] = 0
    row["selectedBedCapacity"]["basis"] = "latest_official_operational_count"
    tampered["capacityReferenceCanonicalSha256"] = canonical_sha256(tampered)
    with pytest.raises(HospitalCapacityReferenceError):
        validate_capacity_reference(tampered)
    tampered = copy.deepcopy(reference)
    tampered["sourceReferences"][0]["sourceUrl"] = "https://example.invalid/tampered"
    with pytest.raises(HospitalCapacityReferenceError, match="hash mismatch"):
        validate_capacity_reference(tampered)
