"""Path containment helpers for P1.4B runtime validation workspaces."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SHARED_DATA_DIR = (ROOT / "data").resolve()


class RuntimeContextError(ValueError):
    """Raised when runtime validation attempts to escape its workspace."""


def require_absolute_directory(value: str | Path, label: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeContextError(f"{label} must be an absolute path.")
    resolved = path.resolve()
    if resolved == SHARED_DATA_DIR or SHARED_DATA_DIR in resolved.parents:
        raise RuntimeContextError(f"{label} cannot use the governed benchmark data directory.")
    return resolved


def require_within(workspace_root: str | Path, value: str | Path, label: str) -> Path:
    workspace = require_absolute_directory(workspace_root, "workspace root")
    path = Path(value)
    if not path.is_absolute():
        raise RuntimeContextError(f"{label} must be an absolute server-generated path.")
    resolved = path.resolve()
    if resolved == workspace or workspace not in resolved.parents:
        raise RuntimeContextError(f"{label} escaped the validation workspace.")
    cursor = resolved.parent
    while cursor != workspace.parent:
        if cursor.exists() and cursor.is_symlink():
            raise RuntimeContextError(f"{label} traverses a symbolic link.")
        if cursor == workspace:
            break
        cursor = cursor.parent
    return resolved
