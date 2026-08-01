import { CheckCircle2, CircleDashed, ShieldAlert } from "lucide-react";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import StatusBadge from "@/components/ui/StatusBadge";
import type { LocalFilePreview, ServerValidationState, WorkflowMode } from "@/lib/forecast-workflow-types";
import type { CurrentModelAssignmentResultSuccess } from "@/lib/runtime/contracts";
import AsyncStatusIndicator from "./AsyncStatusIndicator";

export default function DatasetValidationSummary({ files, mode, serverValidation, onValidate, revalidationRequired, currentAssignment = null, validationActionLabel }: {
  files: Partial<Record<"dengue" | "climate", LocalFilePreview>>;
  mode: WorkflowMode | null;
  serverValidation: ServerValidationState;
  onMode: (mode: WorkflowMode) => void;
  onValidate: () => void;
  revalidationRequired: boolean;
  currentAssignment?: CurrentModelAssignmentResultSuccess | null;
  validationActionLabel?: string;
}) {
  if (!files.dengue || !files.climate) return <EmptyState title="Waiting for both files" description="Choose dengue and climate CSV files to complete the local header preview." />;
  const headerWarnings = [...files.dengue.missingColumns, ...files.climate.missingColumns];
  const isQuickForecast = mode === "quick_forecast";
  return <div className="space-y-4">
    <div className={`rounded-xl border p-5 ${headerWarnings.length ? "border-warning/25 bg-warning/10" : "border-success/25 bg-success/10"}`} role="status">
      <div className="flex gap-3">{headerWarnings.length ? <ShieldAlert className="h-5 w-5 text-warning" /> : <CheckCircle2 className="h-5 w-5 text-success" />}<div><h2 className="font-semibold text-ink">Local preview complete</h2><p className="mt-1 text-sm text-ink-muted">{headerWarnings.length ? "Expected headers are missing. Correct the files before authoritative runtime validation." : "Expected headers were detected. Row content has not been governed or accepted."}</p></div></div>
    </div>
    {revalidationRequired ? <div className="rounded-xl border border-warning/25 bg-warning/10 p-5" role="status"><h3 className="font-semibold text-ink">Workflow revalidation required</h3><p className="mt-1 text-sm text-ink-muted">Runtime workspaces are workflow-specific. Your selected files are retained, but submit them again to validate the newly selected workflow.</p></div> : null}
    <div className="rounded-xl border border-border-subtle bg-surface-muted p-5">
      <h3 className="font-semibold text-ink">{isQuickForecast ? "Authoritative operational validation" : "Authoritative dataset validation"}</h3>
      <p className="mt-1 text-sm text-ink-muted">{isQuickForecast
        ? "Fresh operational forecast validation creates a new governed workspace from the selected local files and binds it to the current governed assignment."
        : "Validate the uploaded dengue and climate datasets against the governed assessment requirements before model assessment begins."}</p>
      {isQuickForecast ? <div className="mt-3 flex flex-wrap gap-2"><Button variant="primary" disabled>Fresh operational validation</Button></div> : null}
      <Button className="mt-4" disabled={!mode || serverValidation.status === "submitting"} onClick={onValidate}>
        {serverValidation.status === "submitting" ? "Validating datasets…" : validationActionLabel ?? "Validate datasets"}
      </Button>
    </div>
    {serverValidation.status === "idle" ? <div className="rounded-xl border border-informational/25 bg-informational/10 p-5"><div className="flex gap-3"><CircleDashed className="h-5 w-5 text-informational" /><div><h3 className="font-semibold text-ink">Server validation not submitted</h3><p className="mt-1 text-sm text-ink-muted">Local preview is not authoritative. Submit both files to check schema, chronology, alignment, and current analytical eligibility.</p></div></div></div> : null}
    {serverValidation.status === "submitting" ? <AsyncStatusIndicator label={isQuickForecast ? "Validating latest data against the current assignment" : "Validating datasets…"} detail="The files are being checked in an isolated server workspace. No forecast is running." delayedAfterSeconds={10} /> : null}
    {serverValidation.status === "failed" ? <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-5" role="alert"><h3 className="font-semibold text-ink">Validation service failed</h3><p className="mt-1 text-sm text-ink-muted">{serverValidation.error.message}</p><p className="mt-2 text-xs text-ink-muted">Reference: {serverValidation.error.correlationId}</p></div> : null}
    {(serverValidation.status === "ready" || serverValidation.status === "invalid") ? <AuthoritativeResult response={serverValidation.response} currentAssignment={currentAssignment} /> : null}
  </div>;
}

function AuthoritativeResult({ response, currentAssignment }: {
  response: Extract<ServerValidationState, { status: "ready" | "invalid" }>["response"];
  currentAssignment: CurrentModelAssignmentResultSuccess | null;
}) {
  const quick = response.eligibility.quickForecast;
  const assess = response.eligibility.assessDataset;
  if (response.workflowMode === "quick_forecast") {
    const authority = response.activeModelAuthority;
    return <div className={`rounded-xl border p-5 ${response.status === "ready" && quick.eligible ? "border-success/25 bg-success/10" : "border-destructive/25 bg-destructive/10"}`} role="status">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-ink">Fresh operational forecast validation: {response.status === "ready" ? "passed" : "invalid"}</h3>
          <p className="mt-1 text-sm text-ink-muted">A new workflow-specific workspace was created. The assessment workspace was not reused.</p>
        </div>
        <StatusBadge label={response.status === "ready" && quick.eligible ? "Operational forecast eligible" : "Operational forecast blocked"} variant={response.status === "ready" && quick.eligible ? "success" : "destructive"} />
      </div>
      <dl className="mt-4 grid gap-2 text-sm text-ink-muted sm:grid-cols-2">
        <div><dt className="font-medium text-ink">New workspace created</dt><dd>{response.workspaceId}</dd></div>
        <div><dt className="font-medium text-ink">Dataset identity</dt><dd>{response.datasetId}</dd></div>
        <div><dt className="font-medium text-ink">Validation status</dt><dd>{response.status}</dd></div>
        <div><dt className="font-medium text-ink">Verified workflow mode</dt><dd>Operational forecast</dd></div>
        <div><dt className="font-medium text-ink">Current governed assignment</dt><dd>{authority && currentAssignment ? "Verified" : "Not available"}</dd></div>
        <div><dt className="font-medium text-ink">Current governed model</dt><dd>{currentAssignment?.selectedCandidateLabel ?? "Not available"}</dd></div>
        <div><dt className="font-medium text-ink">Assignment binding</dt><dd>{authority && currentAssignment && authority.assignmentId === currentAssignment.assignmentId && authority.authoritySnapshotSha256 === currentAssignment.assignmentPointerSha256 ? "Verified" : "Not verified"}</dd></div>
        <div><dt className="font-medium text-ink">Operational forecast eligibility</dt><dd>{quick.eligible ? "Eligible" : "Blocked"}</dd></div>
      </dl>
      {response.issues.length ? <div className="mt-4"><p className="text-sm font-semibold text-ink">Validation warnings or failures</p><ul className="mt-2 space-y-1 text-sm text-ink-muted">{response.issues.map((value, index) => <li key={`${value.code}-${index}`}><span className="font-medium text-ink">{value.severity === "error" ? "Error" : "Warning"}:</span> {value.message}</li>)}</ul></div> : <p className="mt-4 text-sm text-success">No authoritative file, schema, temporal, or alignment errors were found.</p>}
      <p className="mt-4 text-xs text-ink-muted">No operational forecast job was created by validation.</p>
    </div>;
  }
  const compatibility = String(assess.decisionCompatibilityStatus);
  const decisionAvailability = compatibility === "phase1_decision_policy_available"
    ? "Compatible governed one-run decision available after immutable assessment commit"
    : compatibility === "phase2_decision_policy_available"
      ? "Current governed one-run decision available after immutable assessment commit"
      : compatibility === "phase2_decision_policy_not_yet_available"
        ? "Decision policy availability will be resolved from committed assessment evidence"
        : "Decision policy identity unavailable; operator actions fail closed";
  return <div className={`rounded-xl border p-5 ${response.status === "ready" ? "border-success/25 bg-success/10" : "border-destructive/25 bg-destructive/10"}`} role="status">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold text-ink">Authoritative server validation: {response.status === "ready" ? "passed" : "invalid"}</h3><p className="mt-1 text-sm text-ink-muted">{response.counts.overlapWeeks} overlapping weeks · {response.counts.labelledRows} labelled rows</p></div><StatusBadge label={response.status === "ready" ? "Validated" : "Invalid"} variant={response.status === "ready" ? "success" : "destructive"} /></div>
    {response.acceptedPeriod ? <p className="mt-3 text-sm text-ink-muted">Accepted period: {response.acceptedPeriod.start} to {response.acceptedPeriod.end}</p> : null}
    <div className="mt-4 grid gap-3 md:grid-cols-2">
      <div className="rounded-lg border border-border-subtle bg-surface p-4"><p className="font-semibold text-ink">Operational forecast</p><p className="mt-1 text-sm text-ink-muted">Operational forecasting is a separate workflow and does not start from assessment validation.</p>{quick.eligible ? <p className="mt-2 text-xs leading-relaxed text-ink-muted">Compatibility is resolved dynamically from the current governed model assignment.</p> : <ul className="mt-2 space-y-1 text-xs text-ink-muted">{quick.reasons.map(reason => <li key={reason}>• {reason}</li>)}</ul>}<dl className="mt-3 space-y-1 text-xs text-ink-muted"><div><dt className="inline font-medium text-ink">Prediction interval: </dt><dd className="inline">unavailable — model-specific calibration has not yet been completed</dd></div><div><dt className="inline font-medium text-ink">Preparedness: </dt><dd className="inline">{quick.preparednessStatus === "unavailable_missing_planning_policy" ? "unavailable until a planning-scenario policy is approved" : "unavailable for this uploaded dataset"}</dd></div></dl></div>
      <div className="rounded-lg border border-border-subtle bg-surface p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="font-semibold text-ink">Model assessment eligibility</p>
          <StatusBadge label={assess.eligible ? "Dataset assessment eligible" : "Assessment blocked"} variant={assess.eligible ? "success" : "warning"} />
        </div>
        <p className="mt-2 text-sm text-ink-muted">{assess.eligible ? `${assess.plannedFoldCount} temporal folds are governed for the isolated dataset assessment.` : "No assessment or model comparison can start under the current policy decision."}</p>
        <dl className="mt-3 grid gap-1 text-xs text-ink-muted">
          <div><dt className="inline font-medium text-ink">Available folds: </dt><dd className="inline">{assess.availableFoldCount}</dd></div>
          <div><dt className="inline font-medium text-ink">Planned folds: </dt><dd className="inline">{assess.plannedFoldCount || "none"}</dd></div>
          <div><dt className="inline font-medium text-ink">Governed range: </dt><dd className="inline">{assess.minimumFoldCount} minimum / {assess.maximumFoldCount} maximum</dd></div>
          <div><dt className="inline font-medium text-ink">Recent-fold cap: </dt><dd className="inline">{assess.foldCapApplied ? "applied; older rows remain in expanding training" : "not applied"}</dd></div>
          <div><dt className="inline font-medium text-ink">Assessment policy: </dt><dd className="inline">Current governed assessment and decision policy</dd></div>
          <div><dt className="inline font-medium text-ink">Candidate eligibility evidence: </dt><dd className="inline">{Object.keys(assess.candidateEligibility).length} registered candidates checked</dd></div>
          <div><dt className="inline font-medium text-ink">Recommendation governance: </dt><dd className="inline">{assess.recommendationStatus === "evidence_only" ? "technical evidence only; strength not available" : "no recommendation"}</dd></div>
          <div><dt className="inline font-medium text-ink">Assessment decision: </dt><dd className="inline">{decisionAvailability}</dd></div>
        </dl>
        <details className="mt-3 rounded-lg border border-border-subtle bg-surface-muted p-3"><summary className="cursor-pointer text-xs font-semibold text-accent outline-none focus-visible:ring-2 focus-visible:ring-focus">Technical validation evidence</summary><dl className="mt-2 grid gap-1 text-xs text-ink-muted"><div><dt className="inline font-medium text-ink">Policy version: </dt><dd className="inline">{assess.assessmentPolicyVersion}</dd></div><div><dt className="inline font-medium text-ink">Candidate-set eligibility status: </dt><dd className="inline">{assess.candidateSetStatus}</dd></div></dl><ul className="mt-2 space-y-1 text-xs text-ink-muted">{assess.reasons.map((reason, index) => <li key={`${assess.reasonCodes[index] ?? "reason"}-${index}`}>• {reason}</li>)}</ul></details>
        {!assess.eligible && assess.availableFoldCount < assess.minimumFoldCount ? <p className="mt-3 text-xs font-medium text-warning">At least {assess.minimumFoldCount} complete temporal folds are required; this dataset provides {assess.availableFoldCount}.</p> : null}
        <p className="mt-3 text-xs text-ink-muted">Validation and assessment evidence alone do not authorize forecasting. Protected operator actions require trusted server-side ingress, a governed final decision, and an unconsumed one-run authorization.</p>
      </div>
    </div>
    {response.issues.length ? <div className="mt-4"><p className="text-sm font-semibold text-ink">Validation issues</p><ul className="mt-2 space-y-1 text-sm text-ink-muted">{response.issues.map((value, index) => <li key={`${value.code}-${index}`}><span className="font-medium text-ink">{value.severity === "error" ? "Error" : "Warning"}:</span> {value.message}</li>)}</ul></div> : <p className="mt-4 text-sm text-success">No authoritative file, schema, temporal, or alignment errors were found.</p>}
    <p className="mt-4 text-xs text-ink-muted">Workspace {response.workspaceId.slice(0, 8)}… · No model or preparedness process was started.</p>
  </div>;
}
