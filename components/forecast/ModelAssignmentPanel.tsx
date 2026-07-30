"use client";

import { useEffect, useRef, useState } from "react";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import type {
  ApprovedForecastWorkflowState,
  ModelAssignmentPanelStatus,
  ModelAssignmentWorkflowState,
} from "@/lib/forecast-workflow-types";
import {
  getCurrentModelAssignment,
  getRuntimeJob,
  startModelAssignment,
} from "@/lib/runtime/client";
import type {
  CurrentModelAssignmentResultSuccess,
  ModelAssignmentResultSuccess,
  RuntimeErrorResponse,
} from "@/lib/runtime/contracts";
import { statusLabel } from "@/lib/status-labels";
import AsyncStatusIndicator from "./AsyncStatusIndicator";

const MIN_REASON_LENGTH = 12;
const MAX_REASON_LENGTH = 1000;
const SHA = /^[a-f0-9]{64}$/;

type RefreshMode =
  | "initial"
  | "pointer_conflict"
  | "publication_in_progress"
  | "failed_uncertain";

function boundedError(response: RuntimeErrorResponse): string {
  return response.error.message.slice(0, 500);
}

export default function ModelAssignmentPanel({
  approvedForecast,
  selectedCandidateLabel,
  state,
  onStateChange,
}: {
  approvedForecast: ApprovedForecastWorkflowState;
  selectedCandidateLabel: string;
  state: ModelAssignmentWorkflowState;
  onStateChange: (state: ModelAssignmentWorkflowState) => void;
}) {
  const [reason, setReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const publishing = useRef(false);
  const loadedEvidenceKey = useRef<string | null>(null);

  const verifiedApprovedRun = async () => {
    if (
      approvedForecast.status !== "completed"
      || !approvedForecast.jobId
      || !approvedForecast.runId
      || !approvedForecast.committedRunId
      || approvedForecast.runId !== approvedForecast.committedRunId
      || !approvedForecast.sourceDecisionId
      || !approvedForecast.selectedModelId
      || !approvedForecast.approvedForecastCommitSha256
    ) {
      throw new Error("The retained qualification-run evidence is incomplete.");
    }
    const job = await getRuntimeJob(approvedForecast.jobId);
    if (!job.ok) {
      const error = new Error(job.error.message);
      error.name = job.error.code;
      throw error;
    }
    if (
      job.jobKind !== "approved_forecast"
      || job.status !== "completed"
      || job.jobId !== approvedForecast.jobId
      || job.runId !== approvedForecast.runId
      || job.committedRunId !== approvedForecast.committedRunId
      || job.decisionId !== approvedForecast.sourceDecisionId
      || job.approvedForecastCommitSha256 !== approvedForecast.approvedForecastCommitSha256
      || !SHA.test(job.approvedForecastCommitSha256)
    ) {
      throw new Error("The qualification job no longer matches the retained verified evidence.");
    }
  };

  const nextForDifferentCurrent = (
    mode: RefreshMode,
    current: CurrentModelAssignmentResultSuccess,
    message?: string,
  ): ModelAssignmentWorkflowState => {
    const status: ModelAssignmentPanelStatus = mode === "initial" ? "ready" : mode;
    return {
      status,
      current,
      approvedJobVerified: true,
      expectedAssignmentPointerSha256: current.assignmentPointerSha256,
      errorCode: mode === "initial" ? null : mode,
      error: mode === "initial" ? null : message ?? "The current assignment authority differs from this workflow and requires review.",
    };
  };

  const verifyCurrent = async (
    mode: RefreshMode,
    posted?: ModelAssignmentResultSuccess,
    priorPointerSha256?: string,
  ) => {
    try {
      await verifiedApprovedRun();
      const current = await getCurrentModelAssignment();
      if (!current.ok) {
        onStateChange({
          ...state,
          status: current.error.code === "authentication_required" ? "authentication_required" : "failed_uncertain",
          approvedJobVerified: true,
          errorCode: current.error.code,
          error: boundedError(current),
        });
        return;
      }
      const sourceMatches = current.sourceApprovedForecastRunId === approvedForecast.committedRunId;
      const candidateMatches = current.selectedCandidateId === approvedForecast.selectedModelId;
      if (posted) {
        const reconciled = sourceMatches
          && candidateMatches
          && current.assignmentId === posted.assignmentId
          && current.selectedCandidateId === posted.selectedCandidateId
          && current.status === "assigned"
          && SHA.test(current.assignmentPointerSha256)
          && current.assignmentPointerSha256 !== priorPointerSha256;
        onStateChange(reconciled ? {
          status: "assigned_verified",
          current,
          approvedJobVerified: true,
          expectedAssignmentPointerSha256: current.assignmentPointerSha256,
          errorCode: null,
          error: null,
        } : {
          status: "failed_uncertain",
          current,
          approvedJobVerified: true,
          expectedAssignmentPointerSha256: current.assignmentPointerSha256,
          errorCode: "assignment_post_get_reconciliation_failed",
          error: "The assignment response did not reconcile with current server authority.",
        });
        return;
      }
      if (sourceMatches && candidateMatches) {
        onStateChange({
          status: "assigned_verified",
          current,
          approvedJobVerified: true,
          expectedAssignmentPointerSha256: current.assignmentPointerSha256,
          errorCode: null,
          error: null,
        });
        return;
      }
      onStateChange(nextForDifferentCurrent(mode, current));
    } catch (cause) {
      const code = cause instanceof Error ? cause.name : "assignment_read_failed";
      onStateChange({
        ...state,
        status: code === "authentication_required" ? "authentication_required" : "failed_uncertain",
        approvedJobVerified: false,
        errorCode: code,
        error: cause instanceof Error ? cause.message.slice(0, 500) : "Current assignment verification failed.",
      });
    }
  };

  useEffect(() => {
    const evidenceKey = [
      approvedForecast.jobId,
      approvedForecast.committedRunId,
      approvedForecast.approvedForecastCommitSha256,
    ].join("|");
    if (!approvedForecast.jobId || !approvedForecast.committedRunId || loadedEvidenceKey.current === evidenceKey) return;
    loadedEvidenceKey.current = evidenceKey;
    onStateChange({
      ...state,
      status: "loading_current_assignment",
      approvedJobVerified: false,
      errorCode: null,
      error: null,
    });
    void verifyCurrent("initial");
    // Reverification is bound to immutable approved-run evidence, not state refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    approvedForecast.jobId,
    approvedForecast.committedRunId,
    approvedForecast.approvedForecastCommitSha256,
  ]);

  const publish = async () => {
    const trimmedReason = reason.trim();
    const expectedPointer = state.expectedAssignmentPointerSha256;
    if (
      publishing.current
      || state.status !== "ready"
      || !state.approvedJobVerified
      || !expectedPointer
      || !SHA.test(expectedPointer)
      || trimmedReason.length < MIN_REASON_LENGTH
      || trimmedReason.length > MAX_REASON_LENGTH
      || !acknowledged
      || !approvedForecast.committedRunId
      || !approvedForecast.approvedForecastCommitSha256
    ) return;

    publishing.current = true;
    onStateChange({ ...state, status: "publishing", errorCode: null, error: null });
    try {
      const response = await startModelAssignment({
        approvedForecastRunId: approvedForecast.committedRunId,
        expectedApprovedForecastCommitSha256: approvedForecast.approvedForecastCommitSha256,
        expectedAssignmentPointerSha256: expectedPointer,
        reason: trimmedReason,
        assignmentAcknowledged: true,
      });
      if (response.ok) {
        await verifyCurrent("failed_uncertain", response, expectedPointer);
        return;
      }
      if (response.error.code === "authentication_required") {
        onStateChange({ ...state, status: "authentication_required", errorCode: response.error.code, error: boundedError(response) });
        return;
      }
      const mode: RefreshMode = response.error.code === "assignment_pointer_conflict"
        ? "pointer_conflict"
        : response.error.code === "assignment_publication_in_progress"
          ? "publication_in_progress"
          : "failed_uncertain";
      await verifyCurrent(mode);
    } catch {
      await verifyCurrent("failed_uncertain");
    } finally {
      publishing.current = false;
    }
  };

  const refresh = () => {
    if (publishing.current) return;
    const mode: RefreshMode = state.status === "pointer_conflict"
      ? "pointer_conflict"
      : state.status === "publication_in_progress"
        ? "publication_in_progress"
        : "failed_uncertain";
    onStateChange({ ...state, status: "loading_current_assignment", errorCode: null, error: null });
    void verifyCurrent(mode);
  };

  const reasonValid = reason.trim().length >= MIN_REASON_LENGTH && reason.trim().length <= MAX_REASON_LENGTH;
  const immutable = state.status === "assigned_verified";

  return <section className={`rounded-xl border p-5 ${immutable ? "border-success/25 bg-success/10" : "border-border-subtle bg-surface"}`}>
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p className="text-xs font-semibold uppercase tracking-wide text-accent">Governed model assignment</p>
        <h2 className="mt-1 font-semibold text-ink">{immutable?"Current governed model":"Governed assignment proposal"}</h2>
      </div>
      <StatusBadge
        label={statusLabel(state.status)}
        variant={immutable ? "success" : state.status === "failed_uncertain" || state.status === "authentication_required" ? "destructive" : "info"}
      />
    </div>

    <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
      <div><dt className="font-medium text-ink">Qualification evidence</dt><dd className="mt-1 text-ink-muted">Verified run available</dd></div>
      <div><dt className="font-medium text-ink">Pointer read</dt><dd className="mt-1 text-ink-muted">{state.approvedJobVerified && state.expectedAssignmentPointerSha256 ? "Verified current pointer identity available" : "Verification pending"}</dd></div>
      {state.current ? <>
        <div><dt className="font-medium text-ink">Current assignment ID</dt><dd className="mt-1 break-all text-ink-muted">{state.current.assignmentId}</dd></div>
        <div><dt className="font-medium text-ink">{immutable?"Current governed model":"Currently active model"}</dt><dd className="mt-1 text-ink-muted">{state.current.selectedCandidateLabel}</dd></div>
        <div className="md:col-span-2"><dt className="font-medium text-ink">Approved-run relationship</dt><dd className="mt-1 text-ink-muted">{state.current.sourceApprovedForecastRunId === approvedForecast.committedRunId ? "This approved run is the verified source of the current assignment." : "The current assignment came from a different approved run."}</dd></div>
      </> : null}
    </dl>
    {!immutable?<div className="mt-4 rounded-lg border border-border-subtle bg-background p-4 text-sm"><p className="font-medium text-ink">Proposed governed assignment</p><p className="mt-1 text-ink-muted">{selectedCandidateLabel}</p></div>:null}

    <div className="mt-4 rounded-lg border border-warning/25 bg-warning/10 p-4 text-sm text-ink-muted">
      Publishing changes the current governed model assignment. It is deliberate, append-only, and may conflict with another valid publication.
    </div>

    {state.status === "ready" ? <div className="mt-5 space-y-4">
      <label className="block text-sm font-medium text-ink" htmlFor="assignment-reason">
        Assignment reason
        <textarea
          id="assignment-reason"
          className="mt-2 min-h-28 w-full rounded-lg border border-border-subtle bg-surface px-3 py-2 text-sm"
          maxLength={MAX_REASON_LENGTH}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
        />
        <span className="mt-1 block text-xs text-ink-muted">Enter {MIN_REASON_LENGTH}–{MAX_REASON_LENGTH} characters.</span>
      </label>
      <label className="flex items-start gap-3 text-sm text-ink">
        <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
        <span>I acknowledge that this publishes the server-derived candidate from the verified qualification run as the current governed assignment.</span>
      </label>
      <Button disabled={!reasonValid || !acknowledged || state.status !== "ready"} onClick={() => void publish()}>Publish governed assignment</Button>
    </div> : null}

    {state.status === "loading_current_assignment" ? <div className="mt-4 space-y-3"><Button disabled>Verifying current assignment…</Button><AsyncStatusIndicator label="Verifying current model authority" delayedAfterSeconds={10} /></div> : null}
    {state.status === "publishing" ? <div className="mt-4 space-y-3"><Button disabled>Publishing governed assignment…</Button><AsyncStatusIndicator label="Publishing governed assignment" delayedAfterSeconds={10} /></div> : null}
    {state.error ? <p className="mt-4 rounded-lg border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive" role="alert">{state.error}</p> : null}
    {["pointer_conflict", "publication_in_progress", "failed_uncertain"].includes(state.status) ? <div className="mt-4">
      <p className="text-sm text-ink-muted">No assignment retry will occur automatically. Refresh the current authority before deciding what to do next.</p>
      <Button className="mt-3" variant="secondary" disabled={state.status === "publishing"} onClick={refresh}>Refresh current assignment</Button>
    </div> : null}
    {state.status === "authentication_required" ? <p className="mt-4 text-sm text-destructive">Your authenticated session is unavailable. Sign in again, then explicitly refresh; no assignment will be published automatically.</p> : null}
    {immutable ? <div className="mt-5 rounded-lg border border-success/25 bg-surface p-4">
      <p className="font-semibold text-success">Governed assignment verified.</p>
      <p className="mt-1 text-sm text-ink-muted">The assignment was reconciled through current server authority. Model assessment and assignment are complete.</p>
    </div> : null}
  </section>;
}
