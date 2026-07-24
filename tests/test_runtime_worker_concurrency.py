import json
import multiprocessing
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analytics"))

from runtime_commit import RunningJobUpdateError, finalize_running_job, patch_running_job


def _patch_parent(path: str, job_id: str, count: int, start, result) -> None:
    try:
        start.wait()
        for index in range(count):
            patch_running_job(
                Path(path),
                {
                    "workerId": "parent-worker",
                    "processId": os.getpid(),
                    "heartbeatAt": f"parent-heartbeat-{index}",
                    "updatedAt": f"parent-update-{index}",
                },
                expected_job_id=job_id,
            )
        result.put(("parent", "ok", os.getpid()))
    except BaseException as exc:
        result.put(("parent", "error", repr(exc)))
        raise


def _patch_child(path: str, job_id: str, count: int, start, result) -> None:
    try:
        start.wait()
        for index in range(count):
            patch_running_job(
                Path(path),
                {
                    "progress": f"child-progress-{index}",
                    "workflowEvidence": {"childSequence": index},
                    "updatedAt": f"child-update-{index}",
                },
                expected_job_id=job_id,
            )
        result.put(("child", "ok", count - 1))
    except BaseException as exc:
        result.put(("child", "error", repr(exc)))
        raise


def _patch_until_finalized(path: str, job_id: str, started, result) -> None:
    completed = 0
    try:
        for index in range(20_000):
            patch_running_job(
                Path(path),
                {
                    "progress": f"finalizing-child-{index}",
                    "workflowEvidence": {"childSequence": index},
                    "updatedAt": f"child-finalizing-update-{index}",
                },
                expected_job_id=job_id,
            )
            completed += 1
            if index == 0:
                started.set()
    except RunningJobUpdateError as exc:
        result.put(("finalized", completed, str(exc)))
        return
    except BaseException as exc:
        result.put(("error", completed, repr(exc)))
        raise
    result.put(("exhausted", completed, None))


def _running_record(root: Path) -> tuple[Path, str]:
    job_id = str(uuid.uuid4())
    running = root / "jobs" / "running" / f"{job_id}.json"
    running.parent.mkdir(parents=True)
    running.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "jobKind": "dataset_assessment",
                "jobId": job_id,
                "status": "running",
                "progress": "initial",
                "workerId": "initial-worker",
                "processId": 101,
                "heartbeatAt": "initial-heartbeat",
                "updatedAt": "initial-update",
                "workflowEvidence": None,
            }
        ),
        encoding="utf-8",
    )
    return running, job_id


def _spawn_context():
    return multiprocessing.get_context("spawn")


def test_parent_and_child_patches_are_transactional_under_forced_contention():
    with tempfile.TemporaryDirectory() as directory:
        running, job_id = _running_record(Path(directory))
        context = _spawn_context()
        start = context.Event()
        result = context.Queue()
        count = 300
        processes = (
            context.Process(target=_patch_parent, args=(str(running), job_id, count, start, result)),
            context.Process(target=_patch_child, args=(str(running), job_id, count, start, result)),
        )
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(30)
        outcomes = [result.get(timeout=5), result.get(timeout=5)]

        assert [process.exitcode for process in processes] == [0, 0], outcomes
        assert all(outcome[1] == "ok" for outcome in outcomes)
        latest = json.loads(running.read_text(encoding="utf-8"))
        parent_pid = next(outcome[2] for outcome in outcomes if outcome[0] == "parent")
        assert latest["workerId"] == "parent-worker"
        assert latest["processId"] == parent_pid
        assert latest["heartbeatAt"] == f"parent-heartbeat-{count - 1}"
        assert latest["progress"] == f"child-progress-{count - 1}"
        assert latest["workflowEvidence"] == {"childSequence": count - 1}
        assert list(running.parent.glob(f".{running.name}.*.tmp")) == []


def test_field_patches_cannot_republish_stale_snapshots():
    with tempfile.TemporaryDirectory() as directory:
        running, job_id = _running_record(Path(directory))
        stale_child_snapshot = json.loads(running.read_text(encoding="utf-8"))

        patch_running_job(
            running,
            {
                "workerId": "new-parent",
                "processId": 202,
                "heartbeatAt": "new-heartbeat",
                "updatedAt": "new-parent-update",
            },
            expected_job_id=job_id,
        )
        patch_running_job(
            running,
            {
                "progress": "new-child-progress",
                "workflowEvidence": {"basedOn": stale_child_snapshot["updatedAt"]},
                "updatedAt": "new-child-update",
            },
            expected_job_id=job_id,
        )
        patch_running_job(
            running,
            {"heartbeatAt": "newest-heartbeat", "updatedAt": "newest-parent-update"},
            expected_job_id=job_id,
        )

        latest = json.loads(running.read_text(encoding="utf-8"))
        assert latest["workerId"] == "new-parent"
        assert latest["processId"] == 202
        assert latest["heartbeatAt"] == "newest-heartbeat"
        assert latest["progress"] == "new-child-progress"
        assert latest["workflowEvidence"] == {"basedOn": "initial-update"}


@pytest.mark.parametrize("contents", ("{not-json", '{"jobId":"wrong","status":"running"}'))
def test_malformed_or_identity_mismatched_records_fail_closed(contents):
    with tempfile.TemporaryDirectory() as directory:
        running, job_id = _running_record(Path(directory))
        running.write_text(contents, encoding="utf-8")

        with pytest.raises((RunningJobUpdateError, json.JSONDecodeError, RuntimeError)):
            patch_running_job(
                running,
                {"progress": "must-not-publish", "updatedAt": "invalid-update"},
                expected_job_id=job_id,
            )

        assert running.read_text(encoding="utf-8") == contents
        assert list(running.parent.glob(f".{running.name}.*.tmp")) == []


@pytest.mark.parametrize("collection,status", (("completed", "completed"), ("failed", "failed")))
def test_finalization_has_exclusive_ownership_and_late_patches_fail_closed(collection, status):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        running, job_id = _running_record(root)
        patch_running_job(
            running,
            {
                "workerId": "final-parent",
                "processId": 303,
                "heartbeatAt": "pre-final-heartbeat",
                "updatedAt": "pre-final-parent-update",
            },
            expected_job_id=job_id,
        )
        context = _spawn_context()
        started = context.Event()
        result = context.Queue()
        process = context.Process(
            target=_patch_until_finalized,
            args=(str(running), job_id, started, result),
        )
        process.start()
        assert started.wait(10)

        destination = root / "jobs" / collection / running.name
        finalized = finalize_running_job(
            running,
            destination,
            {
                "status": status,
                "progress": status,
                "completedAt": "terminal-time",
                "processId": None,
                "heartbeatAt": "terminal-heartbeat",
                "updatedAt": "terminal-update",
                "error": None if status == "completed" else {"code": "test_failure"},
            },
            expected_job_id=job_id,
        )
        process.join(30)
        outcome = result.get(timeout=5)

        assert process.exitcode == 0, outcome
        assert outcome[0] == "finalized"
        assert not running.exists()
        assert destination.is_file()
        assert len(list((root / "jobs" / "completed").glob("*.json"))) == (1 if status == "completed" else 0)
        assert len(list((root / "jobs" / "failed").glob("*.json"))) == (1 if status == "failed" else 0)
        latest = json.loads(destination.read_text(encoding="utf-8"))
        assert latest == finalized
        assert latest["status"] == status
        assert latest["workerId"] == "final-parent"
        assert latest["heartbeatAt"] == "terminal-heartbeat"
        assert latest["progress"] == status
        assert latest["workflowEvidence"]["childSequence"] >= 0
        with pytest.raises(RunningJobUpdateError, match="no longer exists"):
            patch_running_job(
                running,
                {"progress": "late-patch", "updatedAt": "late-update"},
                expected_job_id=job_id,
            )
        assert not running.exists()
        assert list((root / "jobs").rglob(f".{running.name}.*.tmp")) == []
