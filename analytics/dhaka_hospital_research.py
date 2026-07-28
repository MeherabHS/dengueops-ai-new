"""Bounded official-registry enumeration for governed Dhaka hospital research."""
from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COVERAGE_PATH = ROOT / "artifacts" / "dhaka_government_hospital_coverage.json"
OFFICIAL_HOST = "hris.mohfw.gov.bd"
BASE_QUERY = (
    "https://hris.mohfw.gov.bd/public/facility-registry/reports/organization-list"
    "?division_id%5B%5D=1&district_id%5B%5D=1"
    "&city_corporation_id%5B%5D=1&city_corporation_id%5B%5D=2"
    "&is_private=0&is_active=1&submit=Run"
)
INPATIENT_TYPES = frozenset({
    "31-bed Hospital", "50-bed Hospital", "Chest Disease Hospital", "Combined Military Hospital",
    "Dental College Hospital", "General Hospital (Non District Hospital)", "Hospital of Alternative Medicine",
    "Infectious Disease Hospital", "Maternal & Child Welfare Centre (MCWC)", "Medical College Hospital",
    "Medical University", "Other Hospital", "Postgraduate Institute & Hospital", "Special Purpose Hospital",
    "Specialized Hospital",
})


class DhakaHospitalResearchError(ValueError):
    """Raised when official enumeration cannot be reproduced safely."""


def canonical_sha256(value: dict[str, Any]) -> str:
    content = {key: child for key, child in value.items() if key != "coverageSha256"}
    payload = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_registry_rows(document: str) -> list[dict[str, Any]]:
    rows = []
    for row in re.findall(r"<tr[^>]*>([\s\S]*?)</tr>", document, flags=re.IGNORECASE):
        cells = re.findall(r"<td[^>]*>([\s\S]*?)</td>", row, flags=re.IGNORECASE)
        if len(cells) < 13:
            continue
        values = [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in cells]
        if not values[0].isdigit():
            continue
        rows.append({
            "officialFacilityRegistryId": int(values[0]),
            "officialName": values[1],
            "officialFacilityCode": values[3],
            "agency": values[5],
            "facilityType": values[6],
            "division": values[7],
            "district": values[8],
            "cityCorporation": values[9],
            "upazila": values[10],
            "privateFlag": values[13] if len(values) > 13 else values[12],
        })
    return rows


def classify_registry_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    candidates, excluded = [], []
    seen: set[int] = set()
    for row in rows:
        identity = row["officialFacilityRegistryId"]
        if identity in seen:
            raise DhakaHospitalResearchError("Duplicate official registry identity.")
        seen.add(identity)
        if row["division"] != "Dhaka" or row["district"] != "Dhaka":
            raise DhakaHospitalResearchError("Registry response escaped the governed district filter.")
        if row["cityCorporation"] not in {"Dhaka North City Corperation", "Dhaka South City Corporation"}:
            raise DhakaHospitalResearchError("Registry response escaped the governed city-corporation filter.")
        (candidates if row["facilityType"] in INPATIENT_TYPES else excluded).append(row)
    return {"inpatientCandidates": candidates, "nonInpatientTypeExclusions": excluded}


def fetch_official_registry_pages() -> list[dict[str, Any]]:
    rows = []
    for page in range(1, 5):
        url = f"{BASE_QUERY}&page={page}"
        if urllib.parse.urlparse(url).hostname != OFFICIAL_HOST:
            raise DhakaHospitalResearchError("Official registry host mismatch.")
        request = urllib.request.Request(url, headers={"User-Agent": "DengueOps-governed-research/1.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.geturl().split("/")[2] != OFFICIAL_HOST:
                raise DhakaHospitalResearchError("Official registry redirected to an untrusted host.")
            rows.extend(parse_registry_rows(response.read().decode("utf-8")))
    return rows


def load_coverage(path: str | Path = COVERAGE_PATH) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "schemaVersion", "coverageId", "internalDeploymentId", "deploymentDisplayName",
        "scopeDefinition", "sourceQueries", "researchTimestamp", "totalOfficialRecordsReviewed",
        "detailedInpatientCandidatesReviewed", "includedHospitals", "excludedFacilities",
        "unresolvedFacilities", "duplicateAliasResolutions", "completenessLimitations", "coverageSha256",
    }
    if set(value) != required or value["schemaVersion"] != "1.0" or value["internalDeploymentId"] != "dhaka_south":
        raise DhakaHospitalResearchError("Coverage artifact contract mismatch.")
    if value["coverageSha256"] != canonical_sha256(value):
        raise DhakaHospitalResearchError("Coverage artifact hash mismatch.")
    if value["detailedInpatientCandidatesReviewed"] != (
        len(value["includedHospitals"]) + len(value["excludedFacilities"]) + len(value["unresolvedFacilities"])
    ):
        raise DhakaHospitalResearchError("Coverage candidate accounting mismatch.")
    return value
