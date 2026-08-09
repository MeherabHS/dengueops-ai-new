"""File-backed worker for isolated Quick Forecast and dataset-assessment jobs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from runtime_commit import atomic_json, finalize_running_job, patch_running_job
from runtime_context import ROOT, require_absolute_directory, require_within
from runtime_assessment_commit import verify_committed_runtime_assessment


HEARTBEAT_SECONDS = 15
STALE_SECONDS = 90
DOWNSTREAM_TIMEOUT_SECONDS = 10.0

COLLECTIONS = {
    "dataset_assessment": ("assessments", "assessmentId"),
    "forecast_outcome": ("forecast-outcomes", "outcomeId"),
    "degradation_evidence": ("degradation-evidence", "evidenceId"),
    "model_lifecycle": ("model-lifecycle", "lifecycleDecisionId"),
    "operational_preparedness": ("operational-preparedness", "preparednessId"),
    "quick_forecast": ("runs", "runId"),
    "approved_forecast": ("runs", "runId"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def runtime_root_from_environment() -> Path:
    value = os.environ.get("DENGUEOPS_RUNTIME_ROOT", str(ROOT / "runtime"))
    return require_absolute_directory(value, "runtime root")


def ensure_structure(root: Path) -> None:
    for relative in ("jobs/pending", "jobs/running", "jobs/completed", "jobs/failed", "staging", "runs", "assessment-staging", "assessments", "outcome-staging", "forecast-outcomes", "degradation-staging", "degradation-evidence", "lifecycle-staging", "model-lifecycle", "operational-preparedness-staging", "operational-preparedness", "decisions", "assessment-decisions", "authorizations", "authorization-state", "deployments", "locks"):
        (root / relative).mkdir(parents=True, exist_ok=True)


def load_job(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid runtime job record.")
    schema = json.loads((ROOT / "config" / "runtime_job.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    kind = value.get("jobKind")
    if kind is None:
        if value.get("schemaVersion") != "1.0" or value.get("workflowMode") != "quick_forecast":
            raise ValueError("Invalid runtime job record.")
        kind = "quick_forecast"
    if kind not in {
        "quick_forecast",
        "forecast_outcome",
        "dataset_assessment",
        "approved_forecast",
        "degradation_evidence",
        "model_lifecycle",
        "operational_preparedness",
    }:
        raise ValueError("Invalid runtime job record.")
    identity_field = "assessmentId" if kind == "dataset_assessment" else "outcomeId" if kind == "forecast_outcome" else "evidenceId" if kind == "degradation_evidence" else "lifecycleDecisionId" if kind == "model_lifecycle" else "preparednessId" if kind == "operational_preparedness" else "runId"
    fields = ("jobId", identity_field) if kind in {"forecast_outcome", "degradation_evidence", "model_lifecycle", "operational_preparedness"} else ("jobId", "workspaceId", identity_field)
    for field in fields:
        uuid.UUID(str(value[field]))
    return value


def update_job(path: Path, job: dict[str, Any], **changes: Any) -> dict[str, Any]:
    patch = {**changes, "updatedAt": now()}
    return patch_running_job(path, patch, expected_job_id=str(job["jobId"]))


def finalize_job(path: Path, destination: Path, job: dict[str, Any], **changes: Any) -> dict[str, Any]:
    patch = {**changes, "updatedAt": now()}
    return finalize_running_job(path, destination, patch, expected_job_id=str(job["jobId"]))


def acquire_global_lock(root: Path) -> int | None:
    path = root / "locks" / "analytics.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
        return descriptor
    except FileExistsError:
        return None


def release_global_lock(root: Path, descriptor: int) -> None:
    os.close(descriptor)
    (root / "locks" / "analytics.lock").unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def recover_global_lock(root: Path) -> None:
    lock = root / "locks" / "analytics.lock"
    if not lock.exists():
        return
    try:
        pid = int(lock.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        pid = -1
    if pid <= 0 or not _pid_alive(pid):
        lock.unlink(missing_ok=True)


def terminate_abandoned_pid(pid: int) -> None:
    if pid <= 0 or not _pid_alive(pid):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], shell=False, capture_output=True, timeout=15)
        else:
            os.killpg(pid, signal.SIGTERM)
            time.sleep(2)
            if _pid_alive(pid):
                os.killpg(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass


def claim_one(root: Path) -> Path | None:
    pending = root / "jobs" / "pending"
    running = root / "jobs" / "running"
    for source in sorted(pending.glob("*.json"), key=lambda item: item.stat().st_mtime):
        target = running / source.name
        try:
            os.replace(source, target)
            return target
        except (FileNotFoundError, PermissionError):
            continue
    return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _committed_root(root: Path, job: dict[str, Any]) -> tuple[Path, str]:
    kind = str(job.get("jobKind", "quick_forecast"))
    collection, identity_field = COLLECTIONS[kind]
    identity = str(job[identity_field])
    return root / collection / identity, identity_field


def verify_committed_job_authority(root: Path, job: dict[str, Any]) -> Path:
    committed, identity_field = _committed_root(root, job)
    if job.get("jobKind") == "dataset_assessment":
        verify_committed_runtime_assessment(root, committed, job)
        return committed
    if job.get("jobKind") == "model_lifecycle":
        from runtime_model_lifecycle_commit import recover_committed_bundle
        if recover_committed_bundle(ROOT, root, job) is None:
            raise RuntimeError("Committed lifecycle authority is missing.")
        return committed
    commit_path = committed / "metadata/commit.json"
    if not committed.is_dir() or not commit_path.is_file():
        raise RuntimeError("Committed authority is missing.")
    commit = json.loads(commit_path.read_text(encoding="utf-8"))
    if not isinstance(commit, dict) or commit.get(identity_field) != job.get(identity_field):
        raise RuntimeError("Committed authority identity mismatch.")
    if commit.get("jobId") not in {None, job.get("jobId")} or commit.get("status") not in {None, "committed"}:
        raise RuntimeError("Committed authority job binding mismatch.")
    artifact_hashes = commit.get("artifactHashes", {})
    if not isinstance(artifact_hashes, dict):
        raise RuntimeError("Committed authority hash manifest is invalid.")
    for name, expected in artifact_hashes.items():
        artifact = committed / "artifacts" / str(name)
        if not artifact.is_file() or _sha256(artifact) != expected:
            raise RuntimeError(f"Committed authority artifact hash mismatch: {name}.")

    kind = str(job.get("jobKind", "quick_forecast"))
    pointer = None
    if kind in {"quick_forecast", "approved_forecast"}:
        pointer = root / "deployments" / str(job["deploymentId"]) / "latest.json"
    elif kind == "forecast_outcome":
        pointer = root / "deployments" / str(job["deploymentId"]) / "monitoring/latest.json"
    elif kind == "degradation_evidence":
        version = str(job.get("policyVersion", ""))
        name = f"latest_{version}.json" if version in {"p2-v2", "p2-v3"} else "latest.json"
        pointer = root / "deployments" / str(job["deploymentId"]) / "degradation" / name
    elif kind == "operational_preparedness":
        pointer = root / "deployments" / str(job["deploymentId"]) / "operational-preparedness/latest.json"
    if pointer is not None:
        if not pointer.is_file():
            raise RuntimeError("Committed authority pointer is missing.")
        pointer_value = json.loads(pointer.read_text(encoding="utf-8"))
        if not isinstance(pointer_value, dict):
            raise RuntimeError("Committed authority pointer is invalid.")
        pointer_identity = pointer_value.get(identity_field)
        pointer_is_current = pointer_identity in {None, job.get(identity_field)}
        if not pointer_is_current and commit.get("latestPointerUpdated") is not True:
            raise RuntimeError("Committed authority pointer identity mismatch.")
        pointer_commit_sha = pointer_value.get("commitRecordSha256") or pointer_value.get("commitSha256")
        if pointer_is_current and pointer_commit_sha is not None and pointer_commit_sha != _sha256(commit_path):
            raise RuntimeError("Committed authority pointer hash mismatch.")
    return committed


def _completion(job: dict[str, Any]) -> dict[str, Any]:
    kind = str(job.get("jobKind", "quick_forecast"))
    _, identity_field = COLLECTIONS[kind]
    committed_field = {
        "assessmentId": "committedAssessmentId", "outcomeId": "committedOutcomeId",
        "evidenceId": "committedEvidenceId", "lifecycleDecisionId": "committedLifecycleDecisionId",
        "preparednessId": "committedPreparednessId", "runId": "committedRunId",
    }[identity_field]
    finished = now()
    return {"status": "completed", "progress": "completed", "updatedAt": finished,
            "completedAt": finished, "heartbeatAt": finished, "processId": None, "error": None,
            committed_field: job[identity_field]}


def _complete_existing_job(root: Path, path: Path, job: dict[str, Any]) -> None:
    completed = root / "jobs/completed" / path.name
    completion = _completion(job)
    if path.parent.name == "running":
        finalize_job(path, completed, job, **completion)
    elif job.get("status") in {"failed", "timed_out"} and not completed.exists():
        atomic_json(path, {**job, **completion})
        completed.parent.mkdir(parents=True, exist_ok=True)
        os.replace(path, completed)
    else:
        raise RuntimeError("Committed job is not in a recoverable state.")


def run_bounded_downstream(action: Any, timeout_seconds: float = DOWNSTREAM_TIMEOUT_SECONDS) -> bool:
    finished = threading.Event()
    succeeded = False

    def invoke() -> None:
        nonlocal succeeded
        try:
            action()
            succeeded = True
        except Exception:
            succeeded = False
        finally:
            finished.set()

    threading.Thread(target=invoke, daemon=True, name="dengueops-downstream").start()
    finished.wait(timeout=max(0.0, timeout_seconds))
    return finished.is_set() and succeeded


def dispatch_downstream(root: Path, job: dict[str, Any]) -> dict[str, str]:
    kind = str(job.get("jobKind", "quick_forecast"))
    statuses: dict[str, str] = {}
    if kind in {"quick_forecast", "approved_forecast"}:
        def preparedness() -> None:
            from runtime_operational_preparedness import enqueue_operational_preparedness_job
            enqueue_operational_preparedness_job(root, str(job["deploymentId"]))
        statuses["preparedness"] = "completed" if run_bounded_downstream(preparedness) else "failed_or_timed_out"
    monitoring_required = (
        kind == "dataset_assessment" and job.get("assessmentPolicyVersion") == "p2-v3"
        or kind in {"quick_forecast", "approved_forecast", "forecast_outcome"} and job.get("schemaVersion") == "2.1"
    )
    if monitoring_required:
        def monitoring() -> None:
            from runtime_governed_monitoring import publish_current_monitoring
            expected_run = str(job["runId"]) if kind == "quick_forecast" else None
            publish_current_monitoring(root, expected_run)
        statuses["monitoring"] = "completed" if run_bounded_downstream(monitoring) else "failed_or_timed_out"
    return statuses


def recover_stale_jobs(root: Path) -> None:
    failed = root / "jobs" / "failed"
    recoverable_paths = list((root / "jobs" / "running").glob("*.json"))
    recoverable_paths.extend((root / "jobs" / "failed").glob("*.json"))
    for path in recoverable_paths:
        try:
            job = load_job(path)
            try:
                verify_committed_job_authority(root, job)
            except Exception:
                pass
            else:
                _complete_existing_job(root, path, job)
                dispatch_downstream(root, job)
                continue
            if path.parent.name != "running":
                continue
            heartbeat = job.get("heartbeatAt") or job.get("updatedAt")
            age = time.time() - datetime.fromisoformat(str(heartbeat).replace("Z", "+00:00")).timestamp()
            if age <= STALE_SECONDS:
                continue
            terminate_abandoned_pid(int(job.get("processId") or -1))
            kind = job.get("jobKind", "quick_forecast")
            identity = job["assessmentId"] if kind == "dataset_assessment" else job["outcomeId"] if kind == "forecast_outcome" else job["evidenceId"] if kind == "degradation_evidence" else job["lifecycleDecisionId"] if kind=="model_lifecycle" else job["preparednessId"] if kind=="operational_preparedness" else job["runId"]
            staging = root / ("assessment-staging" if kind == "dataset_assessment" else "outcome-staging" if kind == "forecast_outcome" else "degradation-staging" if kind == "degradation_evidence" else "lifecycle-staging" if kind=="model_lifecycle" else "operational-preparedness-staging" if kind=="operational_preparedness" else "staging") / identity
            if staging.exists():
                quarantine = staging.with_name(f"{identity}.failed-{int(time.time())}")
                os.replace(staging, quarantine)
            finalize_job(path, failed / path.name, job, status="failed", progress="abandoned_job_quarantined", completedAt=now(),
                processId=None, error={"code": "worker_abandoned", "message": "The worker stopped before the run committed.", "retryable": True})
        except Exception:
            continue


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def execute_claimed(root: Path, job_path: Path, worker_id: str) -> None:
    job = load_job(job_path)
    kind = job.get("jobKind", "quick_forecast")
    workspace = None if kind in {"approved_forecast", "forecast_outcome", "degradation_evidence", "model_lifecycle", "operational_preparedness"} else require_within(root, root / "workspaces" / job["workspaceId"], "workspace")
    identity = job["assessmentId"] if kind == "dataset_assessment" else job["outcomeId"] if kind == "forecast_outcome" else job["evidenceId"] if kind == "degradation_evidence" else job["lifecycleDecisionId"] if kind == "model_lifecycle" else job["preparednessId"] if kind == "operational_preparedness" else job["runId"]
    staging_collection = "assessment-staging" if kind == "dataset_assessment" else "outcome-staging" if kind == "forecast_outcome" else "degradation-staging" if kind == "degradation_evidence" else "lifecycle-staging" if kind == "model_lifecycle" else "operational-preparedness-staging" if kind == "operational_preparedness" else "staging"
    staging = require_within(root, root / staging_collection / identity, "staging")
    committed, _ = _committed_root(root, job)
    if committed.is_dir():
        verify_committed_job_authority(root, job)
        _complete_existing_job(root, job_path, job)
        dispatch_downstream(root, job)
        return
    if staging.exists():
        raise RuntimeError("A staging directory already exists for the claimed job.")
    input_root = (root / "assessments" / job["assessmentId"]) if kind == "approved_forecast" else workspace
    input_bytes = 0 if kind in {"forecast_outcome", "degradation_evidence", "model_lifecycle", "operational_preparedness"} else sum((input_root / "inputs" / group / name).stat().st_size for group, name in (
        ("canonical", "dengue_cases.csv"), ("canonical", "climate_data.csv"),
        ("original", "dengue.csv"), ("original", "climate.csv"),
    ))
    minimum_free = 512 * 1024 * 1024 if kind == "dataset_assessment" else 100 * 1024 * 1024
    if shutil.disk_usage(root).free < max(minimum_free, input_bytes * 5):
        raise RuntimeError("Insufficient runtime disk space for isolated analytics execution.")
    (staging / "logs").mkdir(parents=True, exist_ok=False)
    stdout_path, stderr_path = staging / "logs" / "stdout.log", staging / "logs" / "stderr.log"
    started = now()
    initial_progress = "preparing_assessment" if kind == "dataset_assessment" else "preparing_approved_forecast" if kind == "approved_forecast" else "validating_forecast_commit" if kind == "forecast_outcome" else "verifying_monitoring_snapshot" if kind == "degradation_evidence" else "verifying_lifecycle_sources" if kind == "model_lifecycle" else "verifying_preparedness_authorities" if kind == "operational_preparedness" else "preparing_isolated_run"
    job = update_job(job_path, job, status="running", progress=initial_progress, claimedAt=started,
        startedAt=started, heartbeatAt=started, workerId=worker_id, processId=None)
    script = "runtime_assessment.py" if kind == "dataset_assessment" else "runtime_approved_forecast.py" if kind == "approved_forecast" else "runtime_forecast_outcome.py" if kind == "forecast_outcome" else "runtime_model_degradation_evidence.py" if kind == "degradation_evidence" else "runtime_model_lifecycle.py" if kind == "model_lifecycle" else "runtime_operational_preparedness.py" if kind == "operational_preparedness" else "runtime_quick_forecast.py"
    command = [sys.executable, str(ROOT / "analytics" / script), "--runtime-root", str(root), "--job-record", str(job_path)]
    if kind == "approved_forecast": command.extend(["--assessment", str(root / "assessments" / job["assessmentId"])])
    elif kind not in {"forecast_outcome", "degradation_evidence", "model_lifecycle", "operational_preparedness"}: command.extend(["--workspace", str(workspace)])
    command.extend(["--staging", str(staging)])
    capture_root = root / "jobs" / "captures"
    capture_root.mkdir(parents=True, exist_ok=True)
    stdout_capture = capture_root / f"{job['jobId']}.stdout"
    stderr_capture = capture_root / f"{job['jobId']}.stderr"
    timed_out = False
    try:
        with stdout_capture.open("wb") as stdout_stream, stderr_capture.open("wb") as stderr_stream:
            process = subprocess.Popen(command, cwd=ROOT, shell=False, stdout=stdout_stream, stderr=stderr_stream,
                start_new_session=(os.name != "nt"), creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0))
            job = update_job(job_path, job, processId=process.pid)
            deadline = time.monotonic() + int(job["timeoutSeconds"])
            next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    terminate_process(process)
                    break
                if time.monotonic() >= next_heartbeat:
                    job = update_job(job_path, job, heartbeatAt=now())
                    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
                time.sleep(0.25)
        stdout_bytes = stdout_capture.read_bytes()[-1_000_000:]
        stderr_bytes = stderr_capture.read_bytes()[-1_000_000:]
    finally:
        stdout_capture.unlink(missing_ok=True)
        stderr_capture.unlink(missing_ok=True)
    if process.returncode != 0 and staging.exists():
        stdout_path.write_bytes(stdout_bytes[-1_000_000:])
        stderr_path.write_bytes(stderr_bytes[-1_000_000:])
    if timed_out:
        finalize_job(job_path, root / "jobs" / "failed" / job_path.name, job, status="timed_out", progress="timed_out", completedAt=now(), processId=None,
            error={"code": "assessment_timeout" if kind == "dataset_assessment" else "approved_forecast_timeout" if kind == "approved_forecast" else "forecast_outcome_timeout" if kind == "forecast_outcome" else "degradation_evidence_timeout" if kind == "degradation_evidence" else "model_lifecycle_timeout" if kind == "model_lifecycle" else "quick_forecast_timeout",
                "message": "The dataset assessment exceeded its execution limit." if kind == "dataset_assessment" else "The approved forecast exceeded its execution limit." if kind == "approved_forecast" else "Forecast outcome evaluation exceeded its execution limit." if kind == "forecast_outcome" else "Model-degradation evidence generation exceeded its execution limit." if kind == "degradation_evidence" else "The model lifecycle action exceeded its execution limit." if kind == "model_lifecycle" else "The Quick Forecast exceeded its execution limit.", "retryable": kind not in {"approved_forecast","degradation_evidence","model_lifecycle"}})
        return
    if process.returncode != 0:
        marker = stderr_bytes.decode("utf-8", errors="ignore").strip().split("outcome_failure:")[-1].splitlines()[0].split(":") if kind == "forecast_outcome" and b"outcome_failure:" in stderr_bytes else []
        outcome_code = marker[0] if marker else "forecast_outcome_failed"; outcome_retryable = bool(marker and len(marker)>1 and marker[1]=="1")
        finalize_job(job_path, root / "jobs" / "failed" / job_path.name, job, status="failed", progress="execution_failed", completedAt=now(), processId=None,
            error={"code": "assessment_failed" if kind == "dataset_assessment" else "approved_forecast_failed" if kind == "approved_forecast" else outcome_code if kind == "forecast_outcome" else "degradation_evidence_failed" if kind == "degradation_evidence" else "model_lifecycle_failed" if kind == "model_lifecycle" else "quick_forecast_failed",
                "message": "The isolated dataset assessment did not complete." if kind == "dataset_assessment" else "The approved forecast did not complete." if kind == "approved_forecast" else "Forecast outcome evaluation did not complete." if kind == "forecast_outcome" else "Model-degradation evidence generation did not complete." if kind == "degradation_evidence" else "The model lifecycle action did not complete." if kind == "model_lifecycle" else "The isolated Quick Forecast did not complete.", "retryable": outcome_retryable if kind == "forecast_outcome" else kind not in {"approved_forecast","degradation_evidence","model_lifecycle"}})
        return
    try:
        verify_committed_job_authority(root, job)
    except Exception:
        finalize_job(job_path, root / "jobs" / "failed" / job_path.name, job, status="failed", progress="commit_failed", completedAt=now(), processId=None,
            error={"code": "assessment_commit_missing" if kind == "dataset_assessment" else "forecast_outcome_commit_missing" if kind == "forecast_outcome" else "degradation_evidence_commit_missing" if kind == "degradation_evidence" else "model_lifecycle_commit_missing" if kind == "model_lifecycle" else "runtime_commit_missing",
                "message": "The process exited without a valid immutable commit.", "retryable": kind != "model_lifecycle"})
        return
    completion = {"committedAssessmentId": job["assessmentId"]} if kind == "dataset_assessment" else {"committedOutcomeId": job["outcomeId"]} if kind == "forecast_outcome" else {"committedEvidenceId": job["evidenceId"]} if kind == "degradation_evidence" else {"committedLifecycleDecisionId":job["lifecycleDecisionId"]} if kind=="model_lifecycle" else {"committedPreparednessId":job["preparednessId"]} if kind=="operational_preparedness" else {"committedRunId": job["runId"]}
    finalize_job(job_path, root / "jobs" / "completed" / job_path.name, job, status="completed", progress="completed", completedAt=now(), heartbeatAt=now(),
        processId=None, error=None, **completion)
    dispatch_downstream(root, job)


def run_once(root: Path, worker_id: str) -> bool:
    descriptor = acquire_global_lock(root)
    if descriptor is None:
        return False
    try:
        job_path = claim_one(root)
        if job_path is None:
            return False
        release_global_lock(root, descriptor)
        descriptor = None
        try:
            execute_claimed(root, job_path, worker_id)
        except Exception:
            if job_path.exists():
                try:
                    job = load_job(job_path)
                    finalize_job(job_path, root / "jobs" / "failed" / job_path.name, job, status="failed", progress="worker_failed", completedAt=now(), processId=None,
                        error={"code": "runtime_worker_failed", "message": "The runtime worker could not complete the job.", "retryable": True})
                except Exception:
                    pass
        return True
    finally:
        if descriptor is not None:
            release_global_lock(root, descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(description="DengueOps file-backed analytics worker")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--scan-seconds", type=float, default=2.0)
    args = parser.parse_args()
    root = runtime_root_from_environment()
    ensure_structure(root)
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    recover_global_lock(root)
    recover_stale_jobs(root)
    while True:
        worked = run_once(root, worker_id)
        if args.once:
            return 0
        if not worked:
            time.sleep(max(0.25, args.scan_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
