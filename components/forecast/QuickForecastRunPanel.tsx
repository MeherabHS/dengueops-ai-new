"use client";

import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import type {
  QuickForecastWorkflowState,
  QuickValidationReadyEvidence,
} from "@/lib/forecast-workflow-types";
import {
  getLatestDashboard,
  getRuntimeJobByStatusUrl,
  recoverQuickForecastStart,
  startOperationalPreparedness,
  startQuickForecast,
} from "@/lib/runtime/client";
import type { CurrentModelAssignmentResultSuccess, StartQuickForecastRequest } from "@/lib/runtime/contracts";
import AsyncStatusIndicator from "./AsyncStatusIndicator";

const JOB_POLL_INITIAL_MS = 1500;
const JOB_POLL_MAX_MS = 5000;
const JOB_POLL_MAX_TOTAL_MS = 10 * 60 * 1000;
const CURRENT_VERIFY_INITIAL_MS = 1500;
const CURRENT_VERIFY_MAX_MS = 5000;
const CURRENT_VERIFY_MAX_TOTAL_MS = 30_000;

const wait = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export default function QuickForecastRunPanel({
  validation,
  assignment,
  state,
  onStateChange,
  onAssignmentConflict,
  onRequireFreshValidation,
}: {
  validation: QuickValidationReadyEvidence;
  assignment: CurrentModelAssignmentResultSuccess;
  state: QuickForecastWorkflowState;
  onStateChange: (state: QuickForecastWorkflowState) => void;
  onAssignmentConflict: () => void;
  onRequireFreshValidation: () => void;
}) {
  const router = useRouter();
  const mounted = useRef(true);
  const starting = useRef(false);
  const polling = useRef(false);
  const verifyingCurrent = useRef(false);
  const resumedJobKey = useRef<string | null>(null);

  const entryVerified = validation.workflowMode === "quick_forecast"
    && validation.deploymentId === "dhaka_south"
    && validation.assignmentId === assignment.assignmentId
    && validation.assignmentPointerSha256 === assignment.assignmentPointerSha256
    && validation.selectedCandidateId === assignment.selectedCandidateId;

  const request: StartQuickForecastRequest = {
    workspaceId: validation.workspaceId,
    datasetId: validation.datasetId,
    deploymentId: validation.deploymentId,
    validationRecordSha256: validation.validationRecordSha256,
    expectedAssignmentPointerSha256: assignment.assignmentPointerSha256,
  };

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  const setAuthenticationRequired = (message: string, retained?: Partial<QuickForecastWorkflowState>) => {
    onStateChange({
      ...state,
      ...retained,
      status: "authentication_required",
      errorCode: "authentication_required",
      error: message.slice(0, 500),
    });
  };

  const verifyCurrentForecast = async (
    committedRunId: string,
    expectedRunId: string,
    jobId = state.jobId,
    statusUrl = state.statusUrl,
  ) => {
    if (verifyingCurrent.current || committedRunId !== expectedRunId) return;
    verifyingCurrent.current = true;
    const startedAt = Date.now();
    let attempts = 0;
    let delay = CURRENT_VERIFY_INITIAL_MS;
    onStateChange({
      ...state,
      status: "current_verification_pending",
      jobId,
      expectedRunId,
      statusUrl,
      committedRunId,
      currentVerificationStartedAt: new Date(startedAt).toISOString(),
      currentVerificationAttempts: 0,
      exactCurrentRunId: null,
      errorCode: null,
      error: null,
    });
    try {
      while (mounted.current && Date.now() - startedAt <= CURRENT_VERIFY_MAX_TOTAL_MS) {
        attempts += 1;
        const latest = await getLatestDashboard("dhaka_south");
        if (!latest.ok) {
          if (latest.error.code === "authentication_required") {
            setAuthenticationRequired(latest.error.message, { jobId, expectedRunId, statusUrl, committedRunId });
            return;
          }
        } else {
          const exactCurrent = validation.deploymentId === "dhaka_south"
            && latest.sourceType === "uploaded"
            && latest.runId === committedRunId
            && committedRunId === expectedRunId
            && latest.dashboard.latestRun.runId === committedRunId
            && latest.dashboard.modelUse.workflowMode === "quick_forecast";
          if (exactCurrent) {
            const verifiedState: QuickForecastWorkflowState = {
              ...state,
              status: "current_verified",
              jobId,
              expectedRunId,
              statusUrl,
              committedRunId,
              currentVerificationStartedAt: new Date(startedAt).toISOString(),
              currentVerificationAttempts: attempts,
              exactCurrentRunId: committedRunId,
              errorCode: null,
              error: null,
            };
            onStateChange(verifiedState);

            // Preparedness is downstream of the committed forecast. A failure must
            // never invalidate the forecast, but it must not be silently hidden.
            void startOperationalPreparedness()
              .then((preparedness) => {
                if (!mounted.current || preparedness.ok) return;
                onStateChange({
                  ...verifiedState,
                  errorCode: preparedness.error.code,
                  error: `Forecast is current. Preparedness could not be started: ${preparedness.error.message}`.slice(0, 500),
                });
              })
              .catch((reason) => {
                if (!mounted.current) return;
                onStateChange({
                  ...verifiedState,
                  errorCode: "preparedness_start_failed",
                  error: `Forecast is current. Preparedness could not be started: ${reason instanceof Error ? reason.message : "request failed"}`.slice(0, 500),
                });
              });
            return;
          }
        }
        onStateChange({
          ...state,
          status: "current_verification_pending",
          jobId,
          expectedRunId,
          statusUrl,
          committedRunId,
          currentVerificationStartedAt: new Date(startedAt).toISOString(),
          currentVerificationAttempts: attempts,
          exactCurrentRunId: null,
          errorCode: null,
          error: "The committed run is not yet the verified current forecast.",
        });
        await wait(delay);
        delay = Math.min(CURRENT_VERIFY_MAX_MS, Math.round(delay * 1.6));
      }
      if (mounted.current) {
        onStateChange({
          ...state,
          status: "current_verification_timeout",
          jobId,
          expectedRunId,
          statusUrl,
          committedRunId,
          currentVerificationStartedAt: new Date(startedAt).toISOString(),
          currentVerificationAttempts: attempts,
          exactCurrentRunId: null,
          errorCode: "current_forecast_verification_timeout",
          error: "The exact committed run did not become current within 30 seconds. The operational forecast was not rerun.",
        });
      }
    } catch (reason) {
      if (mounted.current) {
        onStateChange({
          ...state,
          status: "failed_uncertain",
          jobId,
          expectedRunId,
          statusUrl,
          committedRunId,
          currentVerificationAttempts: attempts,
          exactCurrentRunId: null,
          errorCode: "current_forecast_verification_failed",
          error: reason instanceof Error ? reason.message.slice(0, 500) : "Current forecast verification failed.",
        });
      }
    } finally {
      verifyingCurrent.current = false;
    }
  };

  const pollJob = async (jobId: string, expectedRunId: string, statusUrl: string) => {
    if (polling.current) return;
    polling.current = true;
    const startedAt = Date.now();
    let delay = JOB_POLL_INITIAL_MS;
    try {
      while (mounted.current && Date.now() - startedAt <= JOB_POLL_MAX_TOTAL_MS) {
        const job = await getRuntimeJobByStatusUrl(statusUrl);
        if (!job.ok) {
          if (job.error.code === "authentication_required") {
            setAuthenticationRequired(job.error.message, { jobId, expectedRunId, statusUrl });
            return;
          }
          throw new Error(job.error.message);
        }
        const authority = job.jobKind === "quick_forecast" ? job.activeModelAuthority : null;
        if (
          job.jobKind !== "quick_forecast"
          || job.jobId !== jobId
          || job.runId !== expectedRunId
          || !authority
          || authority.deploymentId !== "dhaka_south"
          || authority.assignmentId !== assignment.assignmentId
          || authority.authoritySnapshotSha256 !== assignment.assignmentPointerSha256
          || authority.modelId !== assignment.selectedCandidateId
        ) throw new Error("The operational forecast job did not match the verified workspace and assignment authority.");

        if (job.status === "completed") {
          if (!job.committedRunId || job.committedRunId !== expectedRunId) {
            throw new Error("The completed operational forecast job did not commit the expected run.");
          }
          onStateChange({
            ...state,
            status: "committed_pending_current_verification",
            jobId,
            expectedRunId,
            statusUrl,
            committedRunId: job.committedRunId,
            progress: job.progress,
            errorCode: null,
            error: null,
          });
          polling.current = false;
          await verifyCurrentForecast(job.committedRunId, expectedRunId, jobId, statusUrl);
          return;
        }
        if (job.status === "failed") {
          onStateChange({ ...state, status: "job_failed", jobId, expectedRunId, statusUrl, progress: job.progress, errorCode: job.error?.code ?? "quick_forecast_failed", error: job.error?.message ?? "The operational forecast failed." });
          return;
        }
        if (job.status === "cancelled") {
          onStateChange({ ...state, status: "job_cancelled", jobId, expectedRunId, statusUrl, progress: job.progress, errorCode: job.error?.code ?? "quick_forecast_cancelled", error: job.error?.message ?? "The operational forecast was cancelled." });
          return;
        }
        if (job.status === "timed_out") {
          onStateChange({ ...state, status: "job_timed_out", jobId, expectedRunId, statusUrl, progress: job.progress, errorCode: job.error?.code ?? "quick_forecast_timed_out", error: job.error?.message ?? "The operational forecast timed out." });
          return;
        }
        onStateChange({
          ...state,
          status: job.status === "queued" ? "queued" : "running",
          jobId,
          expectedRunId,
          statusUrl,
          progress: job.progress,
          errorCode: null,
          error: null,
        });
        await wait(delay);
        delay = Math.min(JOB_POLL_MAX_MS, Math.round(delay * 1.5));
      }
      if (mounted.current) {
        onStateChange({
          ...state,
          status: "failed_uncertain",
          jobId,
          expectedRunId,
          statusUrl,
          errorCode: "quick_forecast_polling_paused",
          error: "Operational forecast polling paused after the bounded wait. Refresh status without starting another job.",
        });
      }
    } catch (reason) {
      if (mounted.current) {
        onStateChange({
          ...state,
          status: "failed_uncertain",
          jobId,
          expectedRunId,
          statusUrl,
          errorCode: "quick_forecast_job_verification_failed",
          error: reason instanceof Error ? reason.message.slice(0, 500) : "Operational forecast job verification failed.",
        });
      }
    } finally {
      polling.current = false;
    }
  };

  const startOrRecover = async (recovering: boolean) => {
    if (
      starting.current
      || !entryVerified
      || (!recovering && state.status !== "ready_to_run")
      || (recovering && !["publication_in_progress", "failed_uncertain"].includes(state.status))
    ) return;
    starting.current = true;
    onStateChange({
      ...state,
      status: recovering ? "recovering_existing_job" : "starting",
      errorCode: null,
      error: null,
    });
    try {
      const response = recovering
        ? await recoverQuickForecastStart(request)
        : await startQuickForecast(request);
      if (!response.ok) {
        if (response.error.code === "quick_forecast_assignment_conflict") {
          onStateChange({ ...state, status: "assignment_conflict", errorCode: response.error.code, error: response.error.message });
          onAssignmentConflict();
          return;
        }
        if (response.error.code === "quick_forecast_publication_in_progress") {
          onStateChange({ ...state, status: "publication_in_progress", errorCode: response.error.code, error: response.error.message });
          return;
        }
        if (response.error.code === "authentication_required") {
          setAuthenticationRequired(response.error.message);
          return;
        }
        onStateChange({ ...state, status: "failed_uncertain", errorCode: response.error.code, error: response.error.message });
        return;
      }
      const authority = response.activeModelAuthority;
      if (
        response.deploymentId !== "dhaka_south"
        || authority.deploymentId !== "dhaka_south"
        || authority.assignmentId !== assignment.assignmentId
        || authority.authoritySnapshotSha256 !== assignment.assignmentPointerSha256
        || authority.modelId !== assignment.selectedCandidateId
      ) throw new Error("The operational forecast start response did not match the verified assignment authority.");
      const nextStatus = response.recovered ? "recovering_existing_job" : response.status === "queued" ? "queued" : "running";
      onStateChange({
        ...state,
        status: nextStatus,
        jobId: response.jobId,
        expectedRunId: response.runId,
        statusUrl: response.statusUrl,
        committedRunId: null,
        progress: response.status,
        currentVerificationStartedAt: null,
        currentVerificationAttempts: 0,
        exactCurrentRunId: null,
        errorCode: null,
        error: null,
      });
      await pollJob(response.jobId, response.runId, response.statusUrl);
    } catch (reason) {
      onStateChange({
        ...state,
        status: "failed_uncertain",
        errorCode: "quick_forecast_start_uncertain",
        error: reason instanceof Error ? reason.message.slice(0, 500) : "The operational forecast start response was uncertain.",
      });
    } finally {
      starting.current = false;
    }
  };

  useEffect(() => {
    if (!entryVerified || !state.jobId || !state.expectedRunId || !state.statusUrl) return;
    const key = `${state.jobId}:${state.expectedRunId}`;
    if (resumedJobKey.current === key) return;
    resumedJobKey.current = key;
    void pollJob(state.jobId, state.expectedRunId, state.statusUrl);
    // Retained identifiers trigger read-only job verification; no publication is repeated.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entryVerified, state.jobId, state.expectedRunId, state.statusUrl]);

  useEffect(() => {
    if (
      state.status !== "current_verified"
      || !state.committedRunId
      || state.exactCurrentRunId !== state.committedRunId
      || state.committedRunId !== state.expectedRunId
    ) return;
    const timer = window.setTimeout(() => router.push("/dashboard"), 750);
    return () => window.clearTimeout(timer);
  }, [router, state.committedRunId, state.exactCurrentRunId, state.expectedRunId, state.status]);

  const terminalFailure = ["job_failed", "job_cancelled", "job_timed_out"].includes(state.status);
  const busy = ["starting", "queued", "running", "recovering_existing_job", "committed_pending_current_verification", "current_verification_pending"].includes(state.status);

  return <section className="space-y-4 rounded-xl border border-border-subtle bg-surface-muted p-5" aria-labelledby="quick-forecast-run-title">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h3 id="quick-forecast-run-title" className="font-semibold text-ink">Operational forecast execution</h3>
        <p className="mt-1 text-sm text-ink-muted">This action may publish a new current forecast for Dhaka. The assigned model is resolved from verified server authority.</p>
      </div>
      <StatusBadge label={state.status.replaceAll("_", " ")} variant={state.status === "current_verified" ? "success" : terminalFailure || state.status === "assignment_conflict" ? "destructive" : "info"} />
    </div>

    <dl className="grid gap-2 text-sm text-ink-muted sm:grid-cols-2">
      <div><dt className="font-medium text-ink">Current governed assignment</dt><dd>Verified</dd></div>
      <div><dt className="font-medium text-ink">Assigned model</dt><dd>{assignment.selectedCandidateLabel}</dd></div>
      <div><dt className="font-medium text-ink">Fresh validation workspace</dt><dd>Verified</dd></div>
      <div><dt className="font-medium text-ink">Validation status</dt><dd>Ready for operational forecast</dd></div>
    </dl>
    <details className="rounded-lg border border-border-subtle bg-surface p-3"><summary className="cursor-pointer text-xs font-semibold text-accent outline-none focus-visible:ring-2 focus-visible:ring-focus">Technical execution evidence</summary><dl className="mt-2 grid gap-2 text-xs text-ink-muted sm:grid-cols-2"><div><dt className="font-medium text-ink">Assignment ID</dt><dd className="break-all font-mono">{assignment.assignmentId}</dd></div><div><dt className="font-medium text-ink">Candidate ID</dt><dd className="font-mono">{assignment.selectedCandidateId}</dd></div><div><dt className="font-medium text-ink">Workspace ID</dt><dd className="break-all font-mono">{validation.workspaceId}</dd></div><div><dt className="font-medium text-ink">Dataset ID</dt><dd className="break-all font-mono">{validation.datasetId}</dd></div>{state.jobId ? <div><dt className="font-medium text-ink">Job ID</dt><dd className="break-all font-mono">{state.jobId}</dd></div> : null}</dl></details>

    {state.error ? <div className="rounded-lg border border-warning/25 bg-warning/10 p-3 text-sm text-ink-muted" role="status">{state.error}</div> : null}
    {state.progress ? <p className="text-sm text-ink-muted">Progress: {state.progress}</p> : null}
    {busy ? <AsyncStatusIndicator
      label={state.status === "starting"
        ? "Starting forecast…"
        : state.status === "queued" || state.status === "recovering_existing_job"
          ? "Waiting for forecasting worker"
          : state.status === "running"
            ? "Generating forecast with the current assigned model"
            : state.status === "committed_pending_current_verification"
              ? "Verifying committed forecast evidence"
              : "Verifying the completed run as the current forecast"}
      delayedAfterSeconds={state.status === "queued" || state.status === "recovering_existing_job" ? 15 : state.status === "running" ? 30 : 10}
    /> : null}

    {state.status === "ready_to_run" ? <Button disabled={!entryVerified} onClick={() => void startOrRecover(false)}>Run operational forecast</Button> : null}
    {state.status === "publication_in_progress" || state.status === "failed_uncertain" ? <Button onClick={() => void startOrRecover(true)}>Recover operational forecast status</Button> : null}
    {state.status === "current_verification_timeout" && state.committedRunId && state.expectedRunId ? <Button onClick={() => void verifyCurrentForecast(state.committedRunId!, state.expectedRunId!)}>Retry current verification</Button> : null}
    {state.status === "current_verified" && state.committedRunId === state.expectedRunId && state.exactCurrentRunId === state.committedRunId ? <Button onClick={() => router.push("/dashboard")}>Open dashboard</Button> : null}
    {terminalFailure ? <div className="space-y-2"><p className="text-xs text-ink-muted">A retry requires deliberate fresh operational validation in a new workspace. This consumed workspace will not be reused.</p><Button variant="secondary" onClick={onRequireFreshValidation}>Validate a new workspace</Button></div> : null}
    {busy ? <p className="text-xs text-ink-muted">Duplicate execution controls are disabled while the existing governed operation is verified.</p> : null}
  </section>;
}
