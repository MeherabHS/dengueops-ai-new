"use client";

import { useEffect, useRef, useState } from "react";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import AsyncStatusIndicator from "./AsyncStatusIndicator";
import type { ApprovedForecastWorkflowState } from "@/lib/forecast-workflow-types";
import type { AssessmentDecisionWorkflowProjection, DecisionResultSuccess } from "@/lib/runtime/contracts";
import { getRuntimeJob, getRuntimeJobByStatusUrl, startApprovedForecast } from "@/lib/runtime/client";
import { modelLabel, statusLabel } from "@/lib/status-labels";

type RecordedDecision = DecisionResultSuccess | AssessmentDecisionWorkflowProjection;
const SHA = /^[a-f0-9]{64}$/;
const terminal = new Set(["completed", "failed", "timed_out", "cancelled"]);

export async function runQualificationStartOnce<T>(
  guard: { current: boolean },
  setStarting: (starting: boolean) => void,
  operation: () => Promise<T>,
): Promise<T | null> {
  if (guard.current) return null;
  guard.current = true;
  setStarting(true);
  try {
    return await operation();
  } finally {
    guard.current = false;
    setStarting(false);
  }
}

export default function ApprovedForecastPanel({
  decision,
  state,
  onStateChange,
}: {
  decision: RecordedDecision;
  state: ApprovedForecastWorkflowState;
  onStateChange: (state: ApprovedForecastWorkflowState) => void;
}) {
  const polling = useRef(false);
  const startingRef = useRef(false);
  const mounted = useRef(true);
  const [isStartingQualification, setIsStartingQualification] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const selectedModelId = decision.selectedModelId;
  const selectedLabel = selectedModelId ? modelLabel(selectedModelId) : null;
  const authorized = decision.forecastAuthorized && decision.authorizationStatus === "available";

  const poll = async (
    base: ApprovedForecastWorkflowState,
    fetchJob: () => ReturnType<typeof getRuntimeJob>,
  ) => {
    if (polling.current) return;
    polling.current = true;
    let delay = 1500;
    try {
      while (mounted.current) {
        const job = await fetchJob();
        if (!job.ok) throw new Error(job.error.message);
        if (job.jobKind !== "approved_forecast" || job.decisionId !== decision.decisionId || job.runId !== base.runId) {
          throw new Error("The qualification job did not match the retained decision evidence.");
        }
        if (job.status === "completed") {
          if (job.committedRunId !== base.runId || !SHA.test(job.approvedForecastCommitSha256)) {
            throw new Error("The qualification run completed without verified commit evidence.");
          }
          onStateChange({
            ...base,
            status: "completed",
            committedRunId: job.committedRunId,
            approvedForecastCommitSha256: job.approvedForecastCommitSha256,
            progress: job.progress,
            error: null,
          });
          return;
        }
        if (job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") {
          onStateChange({ ...base, status: job.status, progress: job.progress, error: job.error?.message ?? `The qualification run ended with ${job.status}.` });
          return;
        }
        onStateChange({ ...base, status: job.status, progress: job.progress, error: null });
        await new Promise((resolve) => window.setTimeout(resolve, delay));
        delay = Math.min(8000, Math.round(delay * 1.35));
      }
    } catch (reason) {
      if (mounted.current) onStateChange({ ...base, status: "failed", error: reason instanceof Error ? reason.message : "Qualification-run verification failed." });
    } finally {
      polling.current = false;
    }
  };

  useEffect(() => {
    if (!state.jobId || !state.runId || terminal.has(state.status) || state.sourceDecisionId !== decision.decisionId || polling.current) return;
    const base = state;
    void poll(base, () => getRuntimeJob(base.jobId!));
    // Resume only when the retained job identity changes; state progress updates must not start another poller.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.jobId, state.runId, state.sourceDecisionId, decision.decisionId]);

  const generate = async () => {
    if (!authorized || !selectedModelId || polling.current || state.status !== "idle") return;
    const queued: ApprovedForecastWorkflowState = {
      status: "queued",
      jobId: null,
      statusUrl: null,
      runId: null,
      committedRunId: null,
      approvedForecastCommitSha256: null,
      sourceDecisionId: decision.decisionId,
      selectedModelId,
      progress: "approved_forecast_queued",
      error: null,
    };
    try {
      const started = await runQualificationStartOnce(
        startingRef,
        (starting) => {
          if (mounted.current) setIsStartingQualification(starting);
        },
        () => startApprovedForecast(decision.decisionId, {
          expectedDecisionCommitSha256: decision.decisionCommitSha256,
        }),
      );
      if (!started) return;
      if (!started.ok) throw new Error(started.error.message);
      const retained = { ...queued, jobId: started.jobId, statusUrl: started.statusUrl, runId: started.runId };
      onStateChange(retained);
      await poll(retained, () => getRuntimeJobByStatusUrl(started.statusUrl));
    } catch (reason) {
      onStateChange({ ...queued, status: "failed", error: reason instanceof Error ? reason.message : "The qualification run could not be started." });
    }
  };

  const checkStatus = async () => {
    if (!state.jobId || !state.runId) return;
    try {
      const job = await getRuntimeJob(state.jobId);
      if (!job.ok) throw new Error(job.error.message);
      if (job.jobKind !== "approved_forecast" || job.decisionId !== decision.decisionId || job.runId !== state.runId) {
        throw new Error("The qualification job did not match the retained decision evidence.");
      }
      if (job.status === "completed" && job.committedRunId === state.runId && SHA.test(job.approvedForecastCommitSha256)) {
        onStateChange({ ...state, status: "completed", committedRunId: job.committedRunId, approvedForecastCommitSha256: job.approvedForecastCommitSha256, progress: job.progress, error: null });
        return;
      }
      onStateChange({ ...state, status: job.status, progress: job.progress, error: job.error?.message ?? null });
    } catch (reason) {
      onStateChange({ ...state, error: reason instanceof Error ? reason.message.slice(0, 500) : "Qualification status could not be verified." });
    }
  };

  return <section className={`rounded-xl border p-5 ${state.status === "completed" ? "border-success/25 bg-success/10" : "border-border-subtle bg-surface"}`}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-accent">Governed qualification run</p><h2 className="mt-1 font-semibold text-ink">{selectedLabel ?? "Server-resolved candidate unavailable"}</h2></div>
      <StatusBadge label={state.status === "idle" ? statusLabel(decision.authorizationStatus) : statusLabel(state.status)} variant={state.status === "completed" ? "success" : state.status === "failed" ? "destructive" : "info"} />
    </div>
    <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
      <div><dt className="font-medium text-ink">Source decision ID</dt><dd className="mt-1 break-all text-ink-muted">{decision.decisionId}</dd></div>
      <div><dt className="font-medium text-ink">Authorization</dt><dd className="mt-1 text-ink-muted">{authorized ? "Available for one deliberate run" : statusLabel(decision.authorizationStatus)}</dd></div>
      {state.jobId ? <div><dt className="font-medium text-ink">Job ID</dt><dd className="mt-1 break-all text-ink-muted">{state.jobId}</dd></div> : null}
      {state.committedRunId ? <div><dt className="font-medium text-ink">Qualification run</dt><dd className="mt-1 text-ink-muted">Completed and retained as assignment evidence</dd></div> : null}
    </dl>
    {state.progress && state.status !== "completed" ? <p className="mt-3 text-sm text-ink-muted">Status: {statusLabel(state.progress)}</p> : null}
    {state.error ? <p className="mt-3 rounded-lg border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive" role="alert">{state.error}</p> : null}
    <div className="mt-4 rounded-lg border border-border-subtle bg-surface-muted p-4 text-sm text-ink-muted"><p>Executes the governed selected candidate once to verify that it can run and to create evidence required for assignment.</p><ul className="mt-2 space-y-1 text-xs"><li>• It does not publish the normal current forecast.</li><li>• It does not change the active assignment by itself.</li><li>• It does not start operational forecasting.</li></ul></div>
    {state.status === "idle" && !isStartingQualification ? <Button className="mt-4" disabled={!authorized || !selectedModelId} onClick={() => void generate()}>Run qualification</Button> : null}
    {state.status === "idle" && isStartingQualification ? <div className="mt-4 space-y-3"><Button disabled>Starting qualification run…</Button><AsyncStatusIndicator label="Starting qualification run…" delayedAfterSeconds={10} /></div> : null}
    {["queued", "running", "committing"].includes(state.status) ? <div className="mt-4 space-y-3"><Button disabled>{state.status === "queued" ? "Waiting for qualification worker…" : state.status === "running" ? "Qualification run in progress…" : "Verifying qualification evidence…"}</Button><AsyncStatusIndicator label={state.status === "queued" ? "Waiting for qualification worker" : state.status === "running" ? "Executing selected candidate for assignment evidence" : "Verifying qualification evidence"} delayedAfterSeconds={state.status === "queued" ? 15 : state.status === "running" ? 30 : 10} onCheckStatus={() => void checkStatus()} /></div> : null}
    {state.status === "completed" ? <div className="mt-5 rounded-lg border border-success/25 bg-surface p-4"><p className="font-semibold text-success">Ready for governed assignment</p><p className="mt-1 text-sm text-ink-muted">The qualification run is verified and retained as assignment evidence. It did not publish an operational forecast.</p><details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-accent outline-none focus-visible:ring-2 focus-visible:ring-focus">Technical evidence</summary><dl className="mt-2 space-y-1 text-xs text-ink-muted"><div><dt className="inline font-medium text-ink">Qualification run ID: </dt><dd className="inline break-all font-mono">{state.committedRunId}</dd></div><div><dt className="inline font-medium text-ink">Commit SHA-256: </dt><dd className="inline break-all font-mono">{state.approvedForecastCommitSha256}</dd></div></dl></details></div> : null}
  </section>;
}
