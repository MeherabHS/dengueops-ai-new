"""Strict current/stale verifier for operational-preparedness authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from runtime_operational_preparedness import build_artifacts, resolve_authorities


class OperationalPreparednessVerificationError(ValueError):
    pass


def _sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def _json(path: Path) -> dict[str, Any]: return json.loads(path.read_text(encoding="utf-8"))


def verify_current_operational_preparedness(runtime_root: str | Path, deployment_id: str = "dhaka_south") -> dict[str, Any]:
    root = Path(runtime_root).resolve(); latest = root / "deployments" / deployment_id / "operational-preparedness" / "latest.json"
    if not latest.is_file(): raise OperationalPreparednessVerificationError("operational_preparedness_unavailable")
    pointer = _json(latest); authority = resolve_authorities(root, deployment_id)
    if pointer.get("authoritySnapshotSha256") != authority["authoritySnapshotSha256"]: raise OperationalPreparednessVerificationError("operational_preparedness_stale")
    package = root / "operational-preparedness" / str(pointer.get("preparednessId")); summary_path=package/"artifacts"/"preparedness.json"; facilities_path=package/"artifacts"/"facility_preparedness.json"; commit_path=package/"metadata"/"commit.json"
    if (_sha(summary_path),_sha(facilities_path),_sha(commit_path)) != (pointer.get("preparednessArtifactSha256"),pointer.get("facilityPreparednessArtifactSha256"),pointer.get("commitSha256")): raise OperationalPreparednessVerificationError("operational_preparedness_integrity_failure")
    summary=_json(summary_path); facilities=_json(facilities_path); commit=_json(commit_path)
    expected_summary,expected_facilities=build_artifacts(authority,str(pointer["preparednessId"]),str(summary["generatedAt"]))
    if summary!=expected_summary or facilities!=expected_facilities or commit.get("artifactHashes")!={"preparedness.json":_sha(summary_path),"facility_preparedness.json":_sha(facilities_path)} or commit.get("authoritySnapshotSha256")!=authority["authoritySnapshotSha256"]: raise OperationalPreparednessVerificationError("operational_preparedness_integrity_failure")
    return {"pointer":pointer,"pointerSha256":_sha(latest),"summary":summary,"facilities":facilities,"commit":commit,"current":True}
