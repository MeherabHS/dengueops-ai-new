import { CheckCircle2, CircleDashed, ShieldAlert } from "lucide-react";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import StatusBadge from "@/components/ui/StatusBadge";
import type { LocalFilePreview, ServerValidationState, WorkflowMode } from "@/lib/forecast-workflow-types";

export default function DatasetValidationSummary({ files, mode, serverValidation, onMode, onValidate, revalidationRequired }: {
  files: Partial<Record<"dengue" | "climate", LocalFilePreview>>;
  mode: WorkflowMode | null;
  serverValidation: ServerValidationState;
  onMode: (mode: WorkflowMode) => void;
  onValidate: () => void;
  revalidationRequired: boolean;
}) {
  if (!files.dengue || !files.climate) return <EmptyState title="Waiting for both files" description="Choose dengue and climate CSV files to complete the local header preview." />;
  const headerWarnings = [...files.dengue.missingColumns, ...files.climate.missingColumns];
  return <div className="space-y-4">
    <div className={`rounded-xl border p-5 ${headerWarnings.length ? "border-warning/25 bg-warning/10" : "border-success/25 bg-success/10"}`} role="status">
      <div className="flex gap-3">{headerWarnings.length ? <ShieldAlert className="h-5 w-5 text-warning" /> : <CheckCircle2 className="h-5 w-5 text-success" />}<div><h2 className="font-semibold text-ink">Local preview complete</h2><p className="mt-1 text-sm text-ink-muted">{headerWarnings.length ? "Expected headers are missing. Correct the files before authoritative runtime validation." : "Expected headers were detected. Row content has not been governed or accepted."}</p></div></div>
    </div>
    {revalidationRequired ? <div className="rounded-xl border border-warning/25 bg-warning/10 p-5" role="status"><h3 className="font-semibold text-ink">Workflow revalidation required</h3><p className="mt-1 text-sm text-ink-muted">Runtime workspaces are workflow-specific. Your selected files are retained, but submit them again to validate the newly selected workflow.</p></div> : null}
    <div className="rounded-xl border border-border-subtle bg-surface-muted p-5">
      <h3 className="font-semibold text-ink">Authoritative validation intent</h3>
      <p className="mt-1 text-sm text-ink-muted">Choose the intended workflow for this validation workspace. The response reports eligibility for both paths.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant={mode === "quick_forecast" ? "primary" : "secondary"} onClick={() => onMode("quick_forecast")}>Quick Forecast</Button>
        <Button variant={mode === "assess_dataset" ? "primary" : "secondary"} onClick={() => onMode("assess_dataset")}>Assess Dataset</Button>
      </div>
      <Button className="mt-4" disabled={!mode || serverValidation.status === "submitting"} onClick={onValidate}>
        {serverValidation.status === "submitting" ? "Validating datasets…" : "Validate datasets"}
      </Button>
    </div>
    {serverValidation.status === "idle" ? <div className="rounded-xl border border-informational/25 bg-informational/10 p-5"><div className="flex gap-3"><CircleDashed className="h-5 w-5 text-informational" /><div><h3 className="font-semibold text-ink">Server validation not submitted</h3><p className="mt-1 text-sm text-ink-muted">Local preview is not authoritative. Submit both files to check schema, chronology, alignment, and current analytical eligibility.</p></div></div></div> : null}
    {serverValidation.status === "submitting" ? <div className="rounded-xl border border-informational/25 bg-informational/10 p-5" role="status"><div className="flex gap-3"><CircleDashed className="h-5 w-5 text-informational" /><div><h3 className="font-semibold text-ink">Authoritative validation in progress</h3><p className="mt-1 text-sm text-ink-muted">The files are being checked in an isolated server workspace. No forecast is running.</p></div></div></div> : null}
    {serverValidation.status === "failed" ? <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-5" role="alert"><h3 className="font-semibold text-ink">Validation service failed</h3><p className="mt-1 text-sm text-ink-muted">{serverValidation.error.message}</p><p className="mt-2 text-xs text-ink-muted">Reference: {serverValidation.error.correlationId}</p></div> : null}
    {(serverValidation.status === "ready" || serverValidation.status === "invalid") ? <AuthoritativeResult response={serverValidation.response} /> : null}
  </div>;
}

function AuthoritativeResult({ response }: { response: Extract<ServerValidationState, { status: "ready" | "invalid" }>["response"] }) {
  const quick = response.eligibility.quickForecast;
  const assess = response.eligibility.assessDataset;
  return <div className={`rounded-xl border p-5 ${response.status === "ready" ? "border-success/25 bg-success/10" : "border-destructive/25 bg-destructive/10"}`} role="status">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold text-ink">Authoritative server validation: {response.status === "ready" ? "passed" : "invalid"}</h3><p className="mt-1 text-sm text-ink-muted">{response.counts.overlapWeeks} overlapping weeks · {response.counts.labelledRows} labelled rows</p></div><StatusBadge label={response.status === "ready" ? "Validated" : "Invalid"} variant={response.status === "ready" ? "success" : "destructive"} /></div>
    {response.acceptedPeriod ? <p className="mt-3 text-sm text-ink-muted">Accepted period: {response.acceptedPeriod.start} to {response.acceptedPeriod.end}</p> : null}
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      <div className="rounded-lg border border-border-subtle bg-surface p-4"><p className="font-semibold text-ink">Quick Forecast</p><p className="mt-1 text-sm text-ink-muted">{quick.eligible ? "Quick Forecast eligible" : "Not eligible."}</p>{quick.eligible ? <p className="mt-2 text-xs leading-relaxed text-ink-muted">The uploaded dataset matches the current governed deployment contract. Quick Forecast may use the approved Random Forest configuration for a point forecast.</p> : null}<ul className="mt-2 space-y-1 text-xs text-ink-muted">{quick.reasons.map(reason => <li key={reason}>• {reason}</li>)}</ul><dl className="mt-3 space-y-1 text-xs text-ink-muted"><div><dt className="inline font-medium text-ink">Empirical range: </dt><dd className="inline">{quick.uncertaintyStatus === "pending_dataset_specific_calibration" ? "pending dataset-specific calibration" : "unavailable for this uploaded dataset"}</dd></div><div><dt className="inline font-medium text-ink">Preparedness: </dt><dd className="inline">{quick.preparednessStatus === "unavailable_missing_planning_policy" ? "unavailable until a planning-scenario policy is approved" : "unavailable for this uploaded dataset"}</dd></div></dl></div>
      <div className="rounded-lg border border-border-subtle bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold text-ink">Assess Dataset</p>
          <StatusBadge label={assess.eligible ? "Dataset assessment eligible" : "Assessment blocked"} variant={assess.eligible ? "success" : "warning"} />
        </div>
        <p className="mt-2 text-sm text-ink-muted">{assess.eligible ? `${assess.plannedFoldCount} temporal folds are governed for the isolated dataset assessment.` : "No assessment or model comparison can start under the current policy decision."}</p>
        <dl className="mt-3 grid gap-1 text-xs text-ink-muted">
          <div><dt className="inline font-medium text-ink">Available folds: </dt><dd className="inline">{assess.availableFoldCount}</dd></div>
          <div><dt className="inline font-medium text-ink">Planned folds: </dt><dd className="inline">{assess.plannedFoldCount || "none"}</dd></div>
          <div><dt className="inline font-medium text-ink">Candidate set: </dt><dd className="inline">{assess.candidateSetStatus === "complete_candidate_set" ? "all seven governed candidates expected" : assess.candidateSetStatus === "partial_candidate_set" ? "partial candidate set" : "insufficient candidate breadth"}</dd></div>
          <div><dt className="inline font-medium text-ink">Recommendation governance: </dt><dd className="inline">{assess.recommendationStatus === "evidence_only" ? "technical evidence only; strength not available" : "no recommendation"}</dd></div>
          <div><dt className="inline font-medium text-ink">Assessment approval: </dt><dd className="inline">{assess.approvalRequired ? "automatic adoption disabled; a trusted internal one-run decision is evaluated separately after assessment" : "not available"}</dd></div>
        </dl>
        <ul className="mt-3 space-y-1 text-xs text-ink-muted">{assess.reasons.map((reason, index) => <li key={`${assess.reasonCodes[index] ?? "reason"}-${index}`}>• {reason}</li>)}</ul>
        <p className="mt-3 text-xs text-ink-muted">Validation alone produces no folds, candidates, or winner. Assessment, one-run decision recording, and forecast execution each require a later explicit action.</p>
      </div>
    </div>
    {response.issues.length ? <div className="mt-4"><p className="text-sm font-semibold text-ink">Validation issues</p><ul className="mt-2 space-y-1 text-sm text-ink-muted">{response.issues.map((value, index) => <li key={`${value.code}-${index}`}><span className="font-medium text-ink">{value.severity === "error" ? "Error" : "Warning"}:</span> {value.message}</li>)}</ul></div> : <p className="mt-4 text-sm text-success">No authoritative file, schema, temporal, or alignment errors were found.</p>}
    <p className="mt-4 text-xs text-ink-muted">Workspace {response.workspaceId.slice(0, 8)}… · No model or preparedness process was started.</p>
  </div>;
}
