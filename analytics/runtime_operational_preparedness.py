"""Generate operational preparedness strictly downstream of current authorities."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path
from typing import Any

from formula_policy import load_formula_activation_policy, policy_raw_sha256, resolve_active_formula
from formula_registry import governed_registry_raw_sha256, load_governed_formula_registry
from operational_preparedness_policy import canonical_sha256, load_operational_preparedness_policy
from runtime_forecast_outcome_source import verify_forecast_source
from runtime_hospital_inventory_verify import verify_active_inventory
from safe_formula import evaluate_formula_canonical

ROOT = Path(__file__).resolve().parent.parent


class OperationalPreparednessError(ValueError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise OperationalPreparednessError("Governed authority must be a JSON object.")
    return value


def _formula_paths() -> tuple[Path, Path]:
    registry = Path(os.environ.get("DENGUEOPS_OPERATIONAL_FORMULA_REGISTRY_PATH", ROOT / "config" / "inventory_gap_formulas.json"))
    policy = Path(os.environ.get("DENGUEOPS_OPERATIONAL_FORMULA_POLICY_PATH", ROOT / "config" / "deployments" / "dhaka_south" / "formula_activation_policy.json"))
    return registry, policy


def resolve_authorities(runtime_root: Path, deployment_id: str = "dhaka_south") -> dict[str, Any]:
    if not runtime_root.is_absolute() or deployment_id != "dhaka_south":
        raise OperationalPreparednessError("Operational preparedness requires the absolute Dhaka runtime.")
    root = runtime_root.resolve()
    forecast_pointer_path = root / "deployments" / deployment_id / "latest.json"
    forecast_pointer = _json(forecast_pointer_path)
    forecast = verify_forecast_source(root, str(forecast_pointer["runId"]), str(forecast_pointer["commitRecordSha256"]), {"quick_forecast_p2", "approved_forecast_p2"})
    registry_path, formula_policy_path = _formula_paths()
    registry = load_governed_formula_registry(registry_path)
    formula_policy = load_formula_activation_policy(formula_policy_path)
    formula = resolve_active_formula("inventory.gap", policy=formula_policy, registry=registry)
    planning_policy = load_operational_preparedness_policy()
    inventory = verify_active_inventory(root, deployment_id)
    gate = formula_policy["authorityGate"]
    if gate["approvedInventoryId"] != inventory["inventory"]["inventoryId"]:
        raise OperationalPreparednessError("The active formula authority does not approve the current inventory.")
    if planning_policy["deploymentId"] != deployment_id or planning_policy["formulaSlot"] != formula["formulaSlot"]:
        raise OperationalPreparednessError("Operational planning policy scope mismatch.")
    inventory_pointer_path = root / "deployments" / deployment_id / "hospital-inventory" / "latest.json"
    snapshot = {
        "deploymentId": deployment_id,
        "forecastRunId": forecast_pointer["runId"],
        "forecastCommitSha256": forecast_pointer["commitRecordSha256"],
        "forecastPointerSha256": _sha(forecast_pointer_path),
        "formulaId": formula["formulaId"],
        "formulaVersion": formula["formulaVersion"],
        "formulaSha256": formula["formulaSha256"],
        "formulaRegistrySha256": registry["registrySha256"],
        "formulaRegistryRawSha256": governed_registry_raw_sha256(registry_path),
        "formulaActivationPolicyId": formula_policy["policyId"],
        "formulaActivationPolicyVersion": formula_policy["policyVersion"],
        "formulaActivationPolicySha256": formula_policy["policySha256"],
        "formulaActivationPolicyRawSha256": policy_raw_sha256(formula_policy_path),
        "planningPolicyId": planning_policy["policyId"],
        "planningPolicyVersion": planning_policy["policyVersion"],
        "planningPolicySha256": planning_policy["policySha256"],
        "inventoryId": inventory["inventory"]["inventoryId"],
        "inventoryArtifactSha256": inventory["inventoryArtifactSha256"],
        "inventoryCommitSha256": inventory["inventoryCommitSha256"],
        "inventoryPointerSha256": _sha(inventory_pointer_path),
    }
    return {"root": root, "forecastPointer": forecast_pointer, "forecast": forecast, "registry": registry, "formulaPolicy": formula_policy, "formula": formula, "planningPolicy": planning_policy, "inventory": inventory, "snapshot": snapshot, "authoritySnapshotSha256": canonical_sha256(snapshot)}


def _allocations(cases: int, hospitals: list[dict[str, Any]]) -> dict[str, int]:
    known = [row for row in hospitals if isinstance(row.get("selectedBedCapacity"), int) and row["selectedBedCapacity"] >= 0]
    total = sum(row["selectedBedCapacity"] for row in known)
    if total <= 0:
        return {}
    exact = [(row, Decimal(cases) * Decimal(row["selectedBedCapacity"]) / Decimal(total)) for row in known]
    result = {row["hospitalId"]: int(value.to_integral_value(rounding=ROUND_FLOOR)) for row, value in exact}
    remaining = cases - sum(result.values())
    ranked = sorted(exact, key=lambda item: (-(item[1] - Decimal(result[item[0]["hospitalId"]])), item[0]["hospitalId"]))
    for row, _ in ranked[:remaining]:
        result[row["hospitalId"]] += 1
    return result


def build_artifacts(authority: dict[str, Any], preparedness_id: str, generated_at: str) -> tuple[dict[str, Any], dict[str, Any]]:
    uuid.UUID(preparedness_id)
    forecast = authority["forecast"]["forecast"]
    cases = int(forecast["forecastReported"])
    target = str(forecast["targetPeriod"])
    hospitals = [row for row in authority["inventory"]["inventory"]["hospitals"] if row.get("active") is True and row.get("participationStatus") == "included"]
    allocations = _allocations(cases, hospitals)
    expression = authority["formula"]["expression"]
    names = {item["name"] for item in authority["formula"]["inputs"]}
    coefficient = authority["formulaPolicy"]["authorityGate"]["resourcePerCase"]
    rows: list[dict[str, Any]] = []
    for hospital in hospitals:
        capacity = hospital.get("selectedBedCapacity")
        allocated = allocations.get(hospital["hospitalId"])
        if isinstance(capacity, int) and allocated is not None:
            result = int(evaluate_formula_canonical(expression, {"allocatedForecastCases": allocated, "resourcePerCase": coefficient, "availableResource": capacity}, allowed_variables=names))
            metric = {"formulaLabel": "Formula-derived preparedness", "value": result, "unit": authority["formula"]["outputUnit"], "status": "available"}
            state = {"status": "calculated", "reason": "Calculated from the current forecast allocation and official capacity reference; not live availability."}
            suggestion = "No formula-derived capacity-reference gap for this forecast allocation." if result == 0 else f"Review a formula-derived capacity-reference gap of {result} bed units."
        else:
            metric = {"formulaLabel": "Formula-derived preparedness", "value": None, "unit": authority["formula"]["outputUnit"], "status": "unavailable_missing_input"}
            state = {"status": "insufficient_data", "reason": "Not available — required operational input not reported."}
            suggestion = None
        rows.append({
            "hospitalId": hospital["hospitalId"], "hospitalName": hospital["officialName"], "participationStatus": "included",
            "capacityReference": {"value": capacity if isinstance(capacity, int) else None, "status": "available" if isinstance(capacity, int) else "unknown", "sourceLabel": "Official capacity reference"},
            "currentLiveAvailability": {"value": None, "status": "not_reported"},
            "forecastPlanningInput": {"currentForecastCases": cases, "allocatedForecastCases": allocated, "targetPeriod": target},
            "preparednessMetric": metric, "planningState": state, "planningSuggestion": suggestion,
        })
    available = sum(row["preparednessMetric"]["status"] == "available" for row in rows)
    summary = {
        "schemaVersion": "1.0", "preparednessId": preparedness_id, "deploymentId": "dhaka_south", "evidenceClassification": "current_operational_preparedness",
        "operationalCalculationStatus": "completed_with_missing_inputs" if available < len(rows) else "completed", "generatedAt": generated_at,
        "authoritySnapshotSha256": authority["authoritySnapshotSha256"], "sourceAuthority": authority["snapshot"],
        "forecast": {"runId": authority["snapshot"]["forecastRunId"], "forecastCases": cases, "targetPeriod": target},
        "formula": {"formulaId": authority["formula"]["formulaId"], "formulaVersion": authority["formula"]["formulaVersion"], "formulaSha256": authority["formula"]["formulaSha256"], "label": "Formula-derived preparedness", "outputUnit": authority["formula"]["outputUnit"]},
        "summary": {"participatingHospitals": len(rows), "capacityKnownHospitals": available, "capacityUnknownHospitals": len(rows)-available, "calculatedHospitals": available, "unavailableHospitals": len(rows)-available},
        "limitations": ["Official capacity reference is not current live availability.", "Current live availability was not reported.", "Formula-derived values are product planning estimates, not hospital-approved requirements."],
    }
    facilities = {"schemaVersion": "1.0", "preparednessId": preparedness_id, "deploymentId": "dhaka_south", "authoritySnapshotSha256": authority["authoritySnapshotSha256"], "rows": rows}
    return summary, facilities


def write_staging(staging: Path, summary: dict[str, Any], facilities: dict[str, Any]) -> None:
    artifacts = staging / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    for name, value in (("preparedness.json", summary), ("facility_preparedness.json", facilities)):
        (artifacts / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def enqueue_operational_preparedness_job(runtime_root: Path, deployment_id: str = "dhaka_south") -> dict[str, Any]:
    """Idempotently queue the exact server-resolved downstream authority snapshot."""
    root = runtime_root.resolve(); authority = resolve_authorities(root, deployment_id)
    latest = root / "deployments" / deployment_id / "operational-preparedness" / "latest.json"
    if latest.is_file():
        pointer = _json(latest)
        if pointer.get("authoritySnapshotSha256") == authority["authoritySnapshotSha256"]:
            return {"recovered": True, "preparednessId": pointer["preparednessId"], "jobId": None, "status": "completed"}
    requests = latest.parent / "requests"; requests.mkdir(parents=True, exist_ok=True)
    marker_path = requests / f"{authority['authoritySnapshotSha256']}.json"
    if marker_path.is_file():
        marker = _json(marker_path)
        if marker.get("authoritySnapshotSha256") == authority["authoritySnapshotSha256"]:
            return {"recovered": True, "preparednessId": marker["preparednessId"], "jobId": marker["jobId"], "status": "queued"}
        raise OperationalPreparednessError("Preparedness request marker identity mismatch.")
    job_id, preparedness_id = str(uuid.uuid4()), str(uuid.uuid4())
    created = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    marker = {"schemaVersion": "1.0", "jobId": job_id, "preparednessId": preparedness_id, "authoritySnapshotSha256": authority["authoritySnapshotSha256"], "createdAt": created}
    descriptor = os.open(marker_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, (json.dumps(marker, indent=2) + "\n").encode("utf-8")); os.fsync(descriptor)
    finally:
        os.close(descriptor)
    job = {"schemaVersion": "1.0", "jobKind": "operational_preparedness", "jobId": job_id, "preparednessId": preparedness_id, "deploymentId": deployment_id, "workflowMode": "operational_preparedness", "authoritySnapshotSha256": authority["authoritySnapshotSha256"], "status": "queued", "progress": "waiting_for_preparedness_worker", "createdAt": created, "claimedAt": None, "startedAt": None, "updatedAt": created, "completedAt": None, "heartbeatAt": None, "workerId": None, "processId": None, "timeoutSeconds": 300, "retryCount": 0, "error": None, "committedPreparednessId": None}
    pending = root / "jobs" / "pending"; pending.mkdir(parents=True, exist_ok=True)
    job_path = pending / f"{job_id}.json"
    job_descriptor = os.open(job_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(job_descriptor, (json.dumps(job, indent=2) + "\n").encode("utf-8")); os.fsync(job_descriptor)
    finally:
        os.close(job_descriptor)
    return {"recovered": False, "preparednessId": preparedness_id, "jobId": job_id, "status": "queued"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True); parser.add_argument("--job-record", required=True); parser.add_argument("--staging", required=True)
    args = parser.parse_args()
    job = _json(Path(args.job_record)); root = Path(args.runtime_root).resolve(); staging = Path(args.staging).resolve()
    authority = resolve_authorities(root, str(job["deploymentId"]))
    if job["authoritySnapshotSha256"] != authority["authoritySnapshotSha256"]:
        raise OperationalPreparednessError("Preparedness job authority snapshot is stale.")
    generated = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    summary, facilities = build_artifacts(authority, str(job["preparednessId"]), generated)
    write_staging(staging, summary, facilities)
    from runtime_operational_preparedness_commit import commit_staging
    commit_staging(root, staging, job, authority)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"operational_preparedness_failure:{type(exc).__name__}:{exc}", file=sys.stderr)
        raise
