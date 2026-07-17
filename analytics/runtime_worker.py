"""File-backed worker for isolated Quick Forecast and dataset-assessment jobs."""
from __future__ import annotations

import argparse
import json
import os
import signal
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from runtime_commit import atomic_json
from runtime_context import ROOT, require_absolute_directory, require_within


HEARTBEAT_SECONDS = 15
STALE_SECONDS = 90


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def runtime_root_from_environment() -> Path:
    value = os.environ.get("DENGUEOPS_RUNTIME_ROOT", str(ROOT / "runtime"))
    return require_absolute_directory(value, "runtime root")


def ensure_structure(root: Path) -> None:
    for relative in ("jobs/pending", "jobs/running", "jobs/completed", "jobs/failed", "staging", "runs", "assessment-staging", "assessments", "outcome-staging", "forecast-outcomes", "degradation-staging", "degradation-evidence", "lifecycle-staging", "model-lifecycle", "decisions", "assessment-decisions", "authorizations", "authorization-state", "deployments", "locks"):
        (root / relative).mkdir(parents=True, exist_ok=True)


def load_job(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schemaVersion") not in {"1.0", "2.0"}:
        raise ValueError("Invalid runtime job record.")
    kind = value.get("jobKind", "quick_forecast")
    if value.get("schemaVersion") == "2.0" and (kind != "forecast_outcome" or value.get("policyVersion") != "p2-v1"):
        raise ValueError("Invalid runtime job record.")
    identity_field = "assessmentId" if kind == "dataset_assessment" else "outcomeId" if kind == "forecast_outcome" else "evidenceId" if kind == "degradation_evidence" else "lifecycleDecisionId" if kind == "model_lifecycle" else "runId"
    fields = ("jobId", identity_field) if kind in {"forecast_outcome", "degradation_evidence", "model_lifecycle"} else ("jobId", "workspaceId", identity_field)
    for field in fields:
        uuid.UUID(str(value[field]))
    schema = json.loads((ROOT / "config" / "runtime_job.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)
    return value


def update_job(path: Path, job: dict[str, Any], **changes: Any) -> dict[str, Any]:
    latest = load_job(path) if path.exists() else job
    latest.update(changes)
    latest["updatedAt"] = now()
    atomic_json(path, latest)
    return latest


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


def recover_stale_jobs(root: Path) -> None:
    failed = root / "jobs" / "failed"
    for path in (root / "jobs" / "running").glob("*.json"):
        try:
            job = load_job(path)
            heartbeat = job.get("heartbeatAt") or job.get("updatedAt")
            age = time.time() - datetime.fromisoformat(str(heartbeat).replace("Z", "+00:00")).timestamp()
            if age <= STALE_SECONDS:
                continue
            terminate_abandoned_pid(int(job.get("processId") or -1))
            job = update_job(path, job, status="failed", progress="abandoned_job_quarantined", completedAt=now(),
                processId=None, error={"code": "worker_abandoned", "message": "The worker stopped before the run committed.", "retryable": True})
            kind = job.get("jobKind", "quick_forecast")
            identity = job["assessmentId"] if kind == "dataset_assessment" else job["outcomeId"] if kind == "forecast_outcome" else job["evidenceId"] if kind == "degradation_evidence" else job["lifecycleDecisionId"] if kind=="model_lifecycle" else job["runId"]
            staging = root / ("assessment-staging" if kind == "dataset_assessment" else "outcome-staging" if kind == "forecast_outcome" else "degradation-staging" if kind == "degradation_evidence" else "lifecycle-staging" if kind=="model_lifecycle" else "staging") / identity
            if staging.exists():
                quarantine = staging.with_name(f"{identity}.failed-{int(time.time())}")
                os.replace(staging, quarantine)
            os.replace(path, failed / path.name)
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
    workspace = None if kind in {"approved_forecast", "forecast_outcome", "degradation_evidence", "model_lifecycle"} else require_within(root, root / "workspaces" / job["workspaceId"], "workspace")
    identity = job["assessmentId"] if kind == "dataset_assessment" else job["outcomeId"] if kind == "forecast_outcome" else job["evidenceId"] if kind == "degradation_evidence" else job["lifecycleDecisionId"] if kind == "model_lifecycle" else job["runId"]
    staging_collection = "assessment-staging" if kind == "dataset_assessment" else "outcome-staging" if kind == "forecast_outcome" else "degradation-staging" if kind == "degradation_evidence" else "lifecycle-staging" if kind == "model_lifecycle" else "staging"
    staging = require_within(root, root / staging_collection / identity, "staging")
    if staging.exists():
        raise RuntimeError("A staging directory already exists for the claimed job.")
    input_root = (root / "assessments" / job["assessmentId"]) if kind == "approved_forecast" else workspace
    input_bytes = 0 if kind in {"forecast_outcome", "degradation_evidence", "model_lifecycle"} else sum((input_root / "inputs" / group / name).stat().st_size for group, name in (
        ("canonical", "dengue_cases.csv"), ("canonical", "climate_data.csv"),
        ("original", "dengue.csv"), ("original", "climate.csv"),
    ))
    minimum_free = 512 * 1024 * 1024 if kind == "dataset_assessment" else 100 * 1024 * 1024
    if shutil.disk_usage(root).free < max(minimum_free, input_bytes * 5):
        raise RuntimeError("Insufficient runtime disk space for isolated analytics execution.")
    (staging / "logs").mkdir(parents=True, exist_ok=False)
    stdout_path, stderr_path = staging / "logs" / "stdout.log", staging / "logs" / "stderr.log"
    started = now()
    initial_progress = "preparing_assessment" if kind == "dataset_assessment" else "preparing_approved_forecast" if kind == "approved_forecast" else "validating_forecast_commit" if kind == "forecast_outcome" else "verifying_monitoring_snapshot" if kind == "degradation_evidence" else "verifying_lifecycle_sources" if kind == "model_lifecycle" else "preparing_isolated_run"
    job = update_job(job_path, job, status="running", progress=initial_progress, claimedAt=started,
        startedAt=started, heartbeatAt=started, workerId=worker_id, processId=None)
    script = "runtime_assessment.py" if kind == "dataset_assessment" else "runtime_approved_forecast.py" if kind == "approved_forecast" else "runtime_forecast_outcome.py" if kind == "forecast_outcome" else "runtime_model_degradation_evidence.py" if kind == "degradation_evidence" else "runtime_model_lifecycle.py" if kind == "model_lifecycle" else "runtime_quick_forecast.py"
    command = [sys.executable, str(ROOT / "analytics" / script), "--runtime-root", str(root), "--job-record", str(job_path)]
    if kind == "approved_forecast": command.extend(["--assessment", str(root / "assessments" / job["assessmentId"])])
    elif kind not in {"forecast_outcome", "degradation_evidence", "model_lifecycle"}: command.extend(["--workspace", str(workspace)])
    command.extend(["--staging", str(staging)])
    process = subprocess.Popen(command, cwd=ROOT, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=(os.name != "nt"), creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0))
    job = update_job(job_path, job, processId=process.pid, progress="validating_forecast_commit" if kind == "forecast_outcome" else "verifying_monitoring_snapshot" if kind == "degradation_evidence" else "building_features")
    deadline = time.monotonic() + int(job["timeoutSeconds"])
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    timed_out = False
    while process.poll() is None:
        if time.monotonic() >= deadline:
            timed_out = True
            terminate_process(process)
            break
        if time.monotonic() >= next_heartbeat:
            job = update_job(job_path, job, heartbeatAt=now())
            next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
        time.sleep(0.25)
    stdout_bytes, stderr_bytes = process.communicate()
    if process.returncode != 0 and staging.exists():
        stdout_path.write_bytes(stdout_bytes[-1_000_000:])
        stderr_path.write_bytes(stderr_bytes[-1_000_000:])
    if timed_out:
        job = update_job(job_path, job, status="timed_out", progress="timed_out", completedAt=now(), processId=None,
            error={"code": "assessment_timeout" if kind == "dataset_assessment" else "approved_forecast_timeout" if kind == "approved_forecast" else "forecast_outcome_timeout" if kind == "forecast_outcome" else "degradation_evidence_timeout" if kind == "degradation_evidence" else "quick_forecast_timeout",
                "message": "The dataset assessment exceeded its execution limit." if kind == "dataset_assessment" else "The approved forecast exceeded its execution limit." if kind == "approved_forecast" else "Forecast outcome evaluation exceeded its execution limit." if kind == "forecast_outcome" else "Model-degradation evidence generation exceeded its execution limit." if kind == "degradation_evidence" else "The Quick Forecast exceeded its execution limit.", "retryable": kind not in {"approved_forecast","degradation_evidence"}})
        os.replace(job_path, root / "jobs" / "failed" / job_path.name)
        return
    if process.returncode != 0:
        marker = stderr_bytes.decode("utf-8", errors="ignore").strip().split("outcome_failure:")[-1].splitlines()[0].split(":") if kind == "forecast_outcome" and b"outcome_failure:" in stderr_bytes else []
        outcome_code = marker[0] if marker else "forecast_outcome_failed"; outcome_retryable = bool(marker and len(marker)>1 and marker[1]=="1")
        job = update_job(job_path, job, status="failed", progress="execution_failed", completedAt=now(), processId=None,
            error={"code": "assessment_failed" if kind == "dataset_assessment" else "approved_forecast_failed" if kind == "approved_forecast" else outcome_code if kind == "forecast_outcome" else "degradation_evidence_failed" if kind == "degradation_evidence" else "quick_forecast_failed",
                "message": "The isolated dataset assessment did not complete." if kind == "dataset_assessment" else "The approved forecast did not complete." if kind == "approved_forecast" else "Forecast outcome evaluation did not complete." if kind == "forecast_outcome" else "Model-degradation evidence generation did not complete." if kind == "degradation_evidence" else "The isolated Quick Forecast did not complete.", "retryable": outcome_retryable if kind == "forecast_outcome" else kind not in {"approved_forecast","degradation_evidence"}})
        os.replace(job_path, root / "jobs" / "failed" / job_path.name)
        return
    committed_root = root / ("assessments" if kind == "dataset_assessment" else "forecast-outcomes" if kind == "forecast_outcome" else "degradation-evidence" if kind == "degradation_evidence" else "model-lifecycle" if kind == "model_lifecycle" else "runs") / identity
    latest = root / "deployments" / job["deploymentId"] / ("monitoring/latest.json" if kind == "forecast_outcome" else "degradation/latest.json" if kind == "degradation_evidence" else "latest.json")
    assignment_action=kind=="model_lifecycle" and job.get("action") in {"bootstrap_historical_profile","promote_selected_model","rollback_previous_assignment"}
    if kind=="model_lifecycle": latest=root/"deployments"/job["deploymentId"]/"model-assignment/latest.json"
    if not committed_root.exists() or (kind in {"quick_forecast", "approved_forecast", "forecast_outcome", "degradation_evidence"} and not latest.exists()) or (assignment_action and not latest.exists()):
        job = update_job(job_path, job, status="failed", progress="commit_failed", completedAt=now(), processId=None,
            error={"code": "assessment_commit_missing" if kind == "dataset_assessment" else "forecast_outcome_commit_missing" if kind == "forecast_outcome" else "degradation_evidence_commit_missing" if kind == "degradation_evidence" else "runtime_commit_missing",
                "message": "The process exited without a valid immutable commit.", "retryable": True})
        os.replace(job_path, root / "jobs" / "failed" / job_path.name)
        return
    completion = {"committedAssessmentId": job["assessmentId"]} if kind == "dataset_assessment" else {"committedOutcomeId": job["outcomeId"]} if kind == "forecast_outcome" else {"committedEvidenceId": job["evidenceId"]} if kind == "degradation_evidence" else {"committedLifecycleDecisionId":job["lifecycleDecisionId"]} if kind=="model_lifecycle" else {"committedRunId": job["runId"]}
    job = update_job(job_path, job, status="completed", progress="completed", completedAt=now(), heartbeatAt=now(),
        processId=None, error=None, **completion)
    os.replace(job_path, root / "jobs" / "completed" / job_path.name)


def run_once(root: Path, worker_id: str) -> bool:
    descriptor = acquire_global_lock(root)
    if descriptor is None:
        return False
    try:
        job_path = claim_one(root)
        if job_path is None:
            return False
        try:
            execute_claimed(root, job_path, worker_id)
        except Exception:
            if job_path.exists():
                try:
                    job = update_job(job_path, load_job(job_path), status="failed", progress="worker_failed", completedAt=now(), processId=None,
                        error={"code": "runtime_worker_failed", "message": "The runtime worker could not complete the job.", "retryable": True})
                    os.replace(job_path, root / "jobs" / "failed" / job_path.name)
                except Exception:
                    pass
        return True
    finally:
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
