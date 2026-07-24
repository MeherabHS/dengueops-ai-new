from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_active_model import resolve_active_model_p2_v2
from runtime_model_lifecycle_commit import commit_lifecycle_action
from tests.lifecycle_fixtures import build_one_run_chain_p2_v2


def main() -> None:
    action = sys.argv[1]
    if action in {"create", "create-quick"}:
        base = Path(sys.argv[2]).resolve()
        model_id = sys.argv[3]
        chain = build_one_run_chain_p2_v2(base, ROOT, model_id=model_id, override=False)
        result = commit_lifecycle_action(
            chain["runtime"],
            one_run_forecast_run_id=chain["runId"],
            reason=f"Create {model_id} parity fixture",
            operator_identifier="b6-parity",
            acknowledgement=True,
        )
        if not result.get("success"):
            raise RuntimeError(result)
        runtime = Path(chain["runtime"]).resolve()
        authority = resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime)
        value = {"runtime": str(runtime), "authority": authority}
        if action == "create-quick":
            from tests.test_product_v2_quick_forecast import build_ready_workspace
            workspace, dataset_id, validation_sha = build_ready_workspace(runtime)
            value.update({
                "workspaceId": workspace.name,
                "datasetId": dataset_id,
                "validationRecordSha256": validation_sha,
            })
        print(json.dumps(value, sort_keys=True))
        return
    if action == "resolve":
        runtime = Path(sys.argv[2]).resolve()
        authority = resolve_active_model_p2_v2(repository_root=ROOT, runtime_root=runtime)
        print(json.dumps(authority, sort_keys=True))
        return
    raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
