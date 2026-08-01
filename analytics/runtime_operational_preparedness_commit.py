"""Independently verify and commit operational-preparedness evidence."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_operational_preparedness import build_artifacts, resolve_authorities


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def commit_staging(root: Path, staging: Path, job: dict[str, Any], initial_authority: dict[str, Any]) -> dict[str, Any]:
    current = resolve_authorities(root, str(job["deploymentId"]))
    if current["authoritySnapshotSha256"] != initial_authority["authoritySnapshotSha256"] or current["authoritySnapshotSha256"] != job["authoritySnapshotSha256"]:
        raise ValueError("Preparedness source authority changed before commit.")
    summary_path = staging / "artifacts" / "preparedness.json"; facilities_path = staging / "artifacts" / "facility_preparedness.json"
    summary = _json(summary_path); facilities = _json(facilities_path)
    expected_summary, expected_facilities = build_artifacts(current, str(job["preparednessId"]), str(summary["generatedAt"]))
    if summary != expected_summary or facilities != expected_facilities:
        raise ValueError("Preparedness staging calculations failed independent verification.")
    committed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    commit = {"schemaVersion": "1.0", "preparednessId": job["preparednessId"], "jobId": job["jobId"], "deploymentId": job["deploymentId"], "status": "committed", "authoritySnapshotSha256": current["authoritySnapshotSha256"], "sourceAuthority": current["snapshot"], "artifactHashes": {"preparedness.json": _sha(summary_path), "facility_preparedness.json": _sha(facilities_path)}, "committedAt": committed_at}
    metadata = staging / "metadata"; metadata.mkdir(exist_ok=True); commit_path = metadata / "commit.json"; commit_path.write_text(json.dumps(commit, indent=2) + "\n", encoding="utf-8")
    destination = root / "operational-preparedness" / str(job["preparednessId"])
    lock_path = root / "deployments" / str(job["deploymentId"]) / "operational-preparedness" / "locks" / "commit.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        latest = lock_path.parent.parent / "latest.json"
        previous = _sha(latest) if latest.exists() else None
        if destination.exists():
            if _sha(destination / "metadata" / "commit.json") != _sha(commit_path): raise ValueError("Preparedness identity already contains different evidence.")
            shutil.rmtree(staging)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True); os.replace(staging, destination)
        pointer = {"schemaVersion": "1.0", "deploymentId": job["deploymentId"], "preparednessId": job["preparednessId"], "authoritySnapshotSha256": current["authoritySnapshotSha256"], "preparednessArtifactSha256": commit["artifactHashes"]["preparedness.json"], "facilityPreparednessArtifactSha256": commit["artifactHashes"]["facility_preparedness.json"], "commitSha256": _sha(destination / "metadata" / "commit.json"), "forecastRunId": current["snapshot"]["forecastRunId"], "formulaSha256": current["snapshot"]["formulaSha256"], "planningPolicySha256": current["snapshot"]["planningPolicySha256"], "inventoryPointerSha256": current["snapshot"]["inventoryPointerSha256"], "previousPointerSha256": previous, "committedAt": committed_at}
        _write_atomic(latest, pointer)
        return pointer
    finally:
        os.close(fd); lock_path.unlink(missing_ok=True)
