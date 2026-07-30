import StatusBadge from "@/components/ui/StatusBadge";
import { assessmentRunningLabel, statusLabel } from "@/lib/status-labels";
import type { ProcessingStatus, WorkflowMode } from "@/lib/forecast-workflow-types";
import AsyncStatusIndicator from "./AsyncStatusIndicator";

const descriptions: Record<ProcessingStatus, string> = {
  idle: "No runtime job has been started.", validating: "Authoritative server validation is running.", blocked: "The uploaded dataset is not eligible for this workflow.", ready: "The validated workspace is ready to queue.", queued: "Queued for the isolated runtime worker.", running: "The worker is producing governed evidence in isolated storage.", committing: "Runtime evidence is being validated and committed immutably.", completed: "The immutable runtime evidence committed successfully.", failed: "The runtime job failed; no governed authority changed.", timed_out: "The runtime job timed out and produced no committed evidence.", cancelled: "The runtime job was cancelled and produced no committed evidence.",
};

export default function ProcessingState({ status, stage, workflow, candidateCount, onCheckStatus }: { status: ProcessingStatus; stage?: string; workflow: WorkflowMode | null; candidateCount?: number; onCheckStatus?: () => void }) {
  const active = ["validating", "queued", "running", "committing"].includes(status);
  const label = workflow === "assess_dataset"
    ? status === "validating" ? "Validating assessment data…" : status === "queued" ? "Waiting for assessment worker" : status === "running" ? assessmentRunningLabel(candidateCount) : "Committing governed assessment evidence"
    : status === "validating" ? "Validating latest data against the current assignment" : status === "queued" ? "Waiting for forecasting worker" : status === "running" ? "Generating forecast with the current assigned model" : "Verifying committed forecast evidence";
  const delayedAfterSeconds = status === "queued" ? 15 : status === "running" && workflow === "assess_dataset" ? 60 : status === "running" ? 30 : 10;
  return <div className="rounded-xl border border-border-subtle bg-surface p-5" role="status" aria-live="polite"><div className="flex items-center gap-3"><h2 className="font-semibold text-ink">{workflow === "assess_dataset" ? "Dataset assessment" : "Operational forecast"}</h2><StatusBadge label={statusLabel(status)} variant={status === "failed" || status === "timed_out" ? "destructive" : status === "completed" ? "success" : "neutral"} /></div><p className="mt-2 text-sm text-ink-muted">{descriptions[status]}</p>{stage ? <p className="mt-1 text-xs text-text-muted">Stage: {statusLabel(stage)}</p> : null}{active ? <div className="mt-3"><AsyncStatusIndicator label={label} delayedAfterSeconds={delayedAfterSeconds} onCheckStatus={status === "queued" || status === "running" ? onCheckStatus : undefined} /></div> : null}</div>;
}
