"""Resolve one current Quick Forecast pointer, then verify its immutable source."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from runtime_forecast_outcome_source import ForecastSourceError, verify_forecast_source


class HospitalPreparednessSourceError(RuntimeError):
    """Raised when a qualification forecast source is unavailable or unverified."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_current_quick_forecast(runtime_root: str | Path) -> dict[str, Any]:
    root = Path(runtime_root).resolve()
    pointer_path = root / "deployments" / "dhaka_south" / "latest.json"
    try:
        pointer_bytes = pointer_path.read_bytes()
        pointer = json.loads(pointer_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HospitalPreparednessSourceError("forecast_source_unavailable") from exc
    run_id = pointer.get("runId")
    commit_sha = pointer.get("commitRecordSha256")
    commit_path_value = pointer.get("commitRecordPath", f"runs/{run_id}/metadata/commit.json")
    if not isinstance(run_id, str) or not isinstance(commit_sha, str):
        raise HospitalPreparednessSourceError("source_verification_failed")
    commit_path = (root / commit_path_value).resolve()
    if root not in commit_path.parents or sha256_file(commit_path) != commit_sha:
        raise HospitalPreparednessSourceError("source_verification_failed")
    try:
        bundle = verify_forecast_source(root, run_id, commit_sha, {"quick_forecast_p1", "quick_forecast_p2"})
    except ForecastSourceError as exc:
        raise HospitalPreparednessSourceError("source_verification_failed") from exc
    return {
        "pointer": pointer,
        "pointerSha256": hashlib.sha256(pointer_bytes).hexdigest(),
        "runId": run_id,
        "commitSha256": commit_sha,
        "commitPath": commit_path,
        "bundle": bundle,
    }
