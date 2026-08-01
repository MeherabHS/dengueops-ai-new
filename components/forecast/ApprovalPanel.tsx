"use client";

import { useMemo, useState } from "react";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import type {
  AssessmentDecisionWorkflowProjection,
  CurrentSelectableCandidateId,
  DatasetAssessmentResultSuccess,
  DecisionResultSuccess,
  DecisionChoice,
  GovernedDecisionRequest,
} from "@/lib/runtime/contracts";
import { modelLabel } from "@/lib/status-labels";
import AsyncStatusIndicator from "./AsyncStatusIndicator";

const MIN_REASON_LENGTH = 12;
const MAX_REASON_LENGTH = 1000;
export const DEFAULT_TECHNICAL_WINNER_REASON = "Technical winner approved based on the verified governed assessment ranking.";

type RecordedDecision = DecisionResultSuccess | AssessmentDecisionWorkflowProjection;

export default function ApprovalPanel({
  assessment,
  decision,
  workflowDecision = null,
  busy,
  error = null,
  onDecision,
  onGovernedDecision,
}: {
  assessment: DatasetAssessmentResultSuccess;
  decision: RecordedDecision | null;
  workflowDecision?: AssessmentDecisionWorkflowProjection | null;
  busy: boolean;
  error?: string | null;
  onDecision?: (choice: DecisionChoice, reason: string) => void;
  onGovernedDecision?: (request: GovernedDecisionRequest) => void;
  onForecast?: () => void;
}) {
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [winnerNote, setWinnerNote] = useState("");
  const [overrideReason, setOverrideReason] = useState("");
  const [selectedOverride, setSelectedOverride] = useState<CurrentSelectableCandidateId | null>(null);
  const [uncertaintyAcknowledged, setUncertaintyAcknowledged] = useState(false);
  const [winnerNotSelectedAcknowledged, setWinnerNotSelectedAcknowledged] = useState(false);

  const winner = assessment.workflow.candidates.find((candidate) =>
    candidate.modelId === assessment.technicalWinnerModelId
    && candidate.status === "technical_winner"
    && candidate.completionStatus === "complete"
    && candidate.failedFolds === 0
    && candidate.deployableForOneRun,
  );
  const overrideCandidates = useMemo(() => assessment.workflow.candidates.filter((candidate) =>
    candidate.status === "eligible_non_winner"
    && candidate.candidateClass === "learned_model"
    && candidate.completionStatus === "complete"
    && candidate.failedFolds === 0
    && candidate.deployableForOneRun,
  ), [assessment.workflow.candidates]);
  const boundedWinnerNote = winnerNote.trim();
  const boundedOverrideReason = overrideReason.trim();
  const overrideReasonValid = boundedOverrideReason.length >= MIN_REASON_LENGTH && boundedOverrideReason.length <= MAX_REASON_LENGTH;

  const recorded = decision ?? workflowDecision;
  if (recorded) {
    const outcome = "decision" in recorded ? recorded.decision : recorded.outcome;
    const selectedLabel = recorded.selectedModelId ? modelLabel(recorded.selectedModelId) : null;
    return <section className="rounded-xl border border-success/25 bg-success/10 p-5" aria-live="polite">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-ink">Governed model decision recorded</h2>
        <StatusBadge label={outcome === "approve_technical_winner" ? "Technical winner decision" : "Governed override decision"} variant={outcome === "approve_technical_winner" ? "success" : "info"} />
      </div>
      <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <div><dt className="font-medium text-ink">Decision ID</dt><dd className="mt-1 break-all text-ink-muted">{recorded.decisionId}</dd></div>
        <div><dt className="font-medium text-ink">Governed selected candidate</dt><dd className="mt-1 text-ink-muted">{selectedLabel ?? "Unavailable"}</dd></div>
      </dl>
      <p className="mt-3 text-xs text-warning">Qualification-run authorization only. This is not scientific, clinical, institutional, or active-model approval.</p>
    </section>;
  }

  const submitWinner = () => {
    if (!winner || boundedWinnerNote.length > MAX_REASON_LENGTH || !uncertaintyAcknowledged || busy) return;
    const request: GovernedDecisionRequest = {
      decision: "approve_technical_winner",
      expectedAssessmentSummarySha256: assessment.integrity.assessmentSummarySha256,
      reason: boundedWinnerNote || DEFAULT_TECHNICAL_WINNER_REASON,
      uncertaintyLimitationsAcknowledged: true,
    };
    if (onGovernedDecision) onGovernedDecision(request);
    else onDecision?.(request.decision, request.reason);
  };

  const submitOverride = () => {
    const selected = overrideCandidates.find((candidate) => candidate.modelId === selectedOverride);
    if (!selected || !overrideReasonValid || !winnerNotSelectedAcknowledged || !uncertaintyAcknowledged || busy) return;
    const request: GovernedDecisionRequest = {
      decision: "approve_eligible_non_winner",
      expectedAssessmentSummarySha256: assessment.integrity.assessmentSummarySha256,
      selectedModelId: selected.modelId as CurrentSelectableCandidateId,
      reason: boundedOverrideReason,
      technicalWinnerNotSelectedAcknowledged: true,
      uncertaintyLimitationsAcknowledged: true,
    };
    if (onGovernedDecision) onGovernedDecision(request);
    else onDecision?.(request.decision, request.reason);
  };

  return <section className="rounded-xl border border-border-subtle bg-surface p-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-accent">Governed decision</p><h2 className="mt-1 font-semibold text-ink">Technical winner is the default path</h2></div>
      {winner ? <StatusBadge label={modelLabel(winner.modelId)} variant="success" /> : <StatusBadge label="No valid technical winner" variant="warning" />}
    </div>
    <p className="mt-3 text-sm text-ink-muted">The technical winner was derived from this dataset&apos;s governed assessment. The browser does not choose or submit a model ID on this path.</p>
    {!overrideOpen ? <><label className="mt-4 block text-sm font-medium text-ink" htmlFor="winner-audit-note">Optional audit note</label>
    <textarea id="winner-audit-note" value={winnerNote} maxLength={MAX_REASON_LENGTH} disabled={busy} onChange={(event) => setWinnerNote(event.target.value)} className="mt-2 min-h-24 w-full rounded-lg border border-border bg-surface-muted p-3 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus" />
    <p className="mt-1 text-xs text-ink-muted">{boundedWinnerNote.length}/{MAX_REASON_LENGTH} characters. When blank, the governed assessment-ranking reason is recorded.</p></> : null}
    <label className="mt-3 flex items-start gap-2 text-sm text-ink-muted"><input type="checkbox" checked={uncertaintyAcknowledged} disabled={busy} onChange={(event) => setUncertaintyAcknowledged(event.target.checked)} className="mt-1" />I acknowledge the selected model&apos;s uncertainty and limitations for this qualification run.</label>
    {error ? <p className="mt-3 rounded-lg border border-destructive/25 bg-destructive/10 p-3 text-sm text-destructive" role="alert">{error}</p> : null}
    {busy ? <div className="mt-3"><AsyncStatusIndicator label="Recording governed decision" delayedAfterSeconds={10} /></div> : null}

    {!overrideOpen ? <div className="mt-4 flex flex-wrap gap-2">
      <Button disabled={busy || !winner || boundedWinnerNote.length > MAX_REASON_LENGTH || !uncertaintyAcknowledged} onClick={submitWinner}>{busy ? "Publishing governed decision…" : "Approve technical winner"}</Button>
      <Button variant="secondary" disabled={busy || overrideCandidates.length === 0} onClick={() => setOverrideOpen(true)}>Use governed expert override</Button>
    </div> : <div className="mt-5 rounded-xl border border-warning/25 bg-warning/10 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-ink">Governed expert override</h3><Button variant="quiet" disabled={busy} onClick={() => { setOverrideOpen(false); setSelectedOverride(null); setOverrideReason(""); setWinnerNotSelectedAcknowledged(false); }}>Cancel override</Button></div>
      <p className="mt-2 text-sm text-ink-muted"><span className="font-medium text-ink">Technical winner:</span> {winner ? modelLabel(winner.modelId) : "Unavailable"}</p>
      <label className="mt-3 block text-sm font-medium text-ink" htmlFor="governed-override-candidate">Select eligible alternative</label>
      <select id="governed-override-candidate" value={selectedOverride ?? ""} disabled={busy} onChange={(event) => {
        const selected = overrideCandidates.find((candidate) => candidate.modelId === event.target.value);
        setSelectedOverride(selected ? selected.modelId as CurrentSelectableCandidateId : null);
      }} className="mt-2 min-h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-ink">
        <option value="">Select an eligible non-winner</option>
        {overrideCandidates.map((candidate) => <option key={candidate.modelId} value={candidate.modelId}>{modelLabel(candidate.modelId)}</option>)}
      </select>
      <label className="mt-3 block text-sm font-medium text-ink" htmlFor="override-justification">Override justification *</label>
      <textarea id="override-justification" value={overrideReason} minLength={MIN_REASON_LENGTH} maxLength={MAX_REASON_LENGTH} required disabled={busy} onChange={(event) => setOverrideReason(event.target.value)} className="mt-2 min-h-24 w-full rounded-lg border border-border bg-surface p-3 text-sm text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus" />
      <p className="mt-1 text-xs text-ink-muted">{boundedOverrideReason.length}/{MAX_REASON_LENGTH} characters; at least {MIN_REASON_LENGTH} required.</p>
      <label className="mt-3 flex items-start gap-2 text-sm text-ink-muted"><input type="checkbox" checked={winnerNotSelectedAcknowledged} disabled={busy} onChange={(event) => setWinnerNotSelectedAcknowledged(event.target.checked)} className="mt-1" />I acknowledge that this selection overrides the technical winner.</label>
      <Button className="mt-4" disabled={busy || !selectedOverride || !overrideReasonValid || !winnerNotSelectedAcknowledged || !uncertaintyAcknowledged} onClick={submitOverride}>{busy ? "Publishing governed decision…" : "Approve governed override"}</Button>
    </div>}
  </section>;
}
