from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_worker import run_once
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime


def main() -> int:
    base = Path(sys.argv[1]).resolve()
    runtime, _workspace, _pending, job = build_ready_assessment_runtime(base, source_rows=164)
    if not run_once(runtime, "phase-b-fixture-worker"):
        raise RuntimeError("Phase B assessment fixture did not execute")
    assessment = runtime / "assessments" / job["assessmentId"]
    summary_path = assessment / "artifacts/assessment_summary.json"
    summary = json.loads(summary_path.read_text())
    import hashlib
    print(json.dumps({"runtime":str(runtime),"assessmentId":job["assessmentId"],
                      "summarySha256":hashlib.sha256(summary_path.read_bytes()).hexdigest(),
                      "winner":summary["technicalWinnerModelId"],
                      "eligibleNonWinner":next(candidate["modelId"] for candidate in summary["candidates"] if candidate.get("status")=="eligible_non_winner"),
                      "baseline":next(candidate["modelId"] for candidate in summary["candidates"] if candidate.get("status")=="baseline_only")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
