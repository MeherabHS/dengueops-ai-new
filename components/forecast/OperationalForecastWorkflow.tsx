"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import DatasetUploadPanel from "./DatasetUploadPanel";
import DatasetValidationSummary from "./DatasetValidationSummary";
import ForecastRunStepper from "./ForecastRunStepper";
import QuickForecastRunPanel from "./QuickForecastRunPanel";
import AsyncStatusIndicator from "./AsyncStatusIndicator";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import type {
  LocalFilePreview,
  OperationalForecastStep,
  QuickForecastWorkflowState,
  QuickValidationReadyEvidence,
  ServerValidationState,
} from "@/lib/forecast-workflow-types";
import { getCurrentModelAssignment, validateAssessedDataset, validateRuntimeDatasets } from "@/lib/runtime/client";
import type { CurrentModelAssignmentResultSuccess, RuntimeCandidateId, RuntimeValidationResponseSuccess } from "@/lib/runtime/contracts";
import { modelLabel } from "@/lib/status-labels";

const STORAGE_KEY = "dengueops-operational-forecast-workflow-v1";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const CANDIDATES = new Set<RuntimeCandidateId>([
  "moving_average_4w", "seasonal_naive_52w", "ridge_regression", "poisson_regression",
  "random_forest", "gradient_boosting", "elastic_net", "negative_binomial_regression",
  "extra_trees", "hist_gradient_boosting", "poisson_gam", "previous_week_naive",
]);
const RECOVERABLE_QUICK_FORECAST_STATUSES = new Set<QuickForecastWorkflowState["status"]>([
  "queued",
  "running",
  "recovering_existing_job",
  "publication_in_progress",
  "committed_pending_current_verification",
  "current_verification_pending",
  "current_verification_timeout",
  "authentication_required",
]);

function assessedDatasetFailureHeading(code: string): string {
  if (code === "assessment_dataset_source_unavailable") return "Source assessment unavailable";
  if (code === "assessment_dataset_integrity_failed") return "Dataset integrity verification failed";
  if (code === "assessment_dataset_incompatible" || code === "quick_validation_authority_mismatch") return "Dataset incompatible with current assignment";
  if (code === "python_executable_not_configured") return "Worker unavailable";
  return "Operational validation failed";
}

const emptyQuickForecast: QuickForecastWorkflowState = {
  status: "ready_to_run",
  jobId: null,
  expectedRunId: null,
  statusUrl: null,
  committedRunId: null,
  progress: null,
  currentVerificationStartedAt: null,
  currentVerificationAttempts: 0,
  exactCurrentRunId: null,
  errorCode: null,
  error: null,
};

interface RetainedOperationalWorkflow {
  validation?: QuickValidationReadyEvidence;
  quickForecast?: Partial<QuickForecastWorkflowState>;
}

function boundedValidation(value: unknown): QuickValidationReadyEvidence | null {
  if (!value || typeof value !== "object") return null;
  const evidence = value as Partial<QuickValidationReadyEvidence>;
  if (
    !UUID.test(String(evidence.workspaceId ?? ""))
    || typeof evidence.datasetId !== "string"
    || evidence.datasetId.length === 0
    || evidence.datasetId.length > 160
    || !SHA.test(String(evidence.validationRecordSha256 ?? ""))
    || evidence.workflowMode !== "quick_forecast"
    || evidence.deploymentId !== "dhaka_south"
    || !UUID.test(String(evidence.assignmentId ?? ""))
    || !SHA.test(String(evidence.assignmentPointerSha256 ?? ""))
    || !CANDIDATES.has(evidence.selectedCandidateId as RuntimeCandidateId)
  ) return null;
  return evidence as QuickValidationReadyEvidence;
}

function boundedQuickForecast(value: unknown): QuickForecastWorkflowState | null {
  if (!value || typeof value !== "object") return null;
  const retained = value as Partial<QuickForecastWorkflowState>;
  const jobId = UUID.test(String(retained.jobId ?? "")) ? retained.jobId! : null;
  const expectedRunId = UUID.test(String(retained.expectedRunId ?? "")) ? retained.expectedRunId! : null;
  const statusUrl = jobId && retained.statusUrl === `/api/runtime/jobs/${jobId}` ? retained.statusUrl : null;
  if (!jobId || !expectedRunId || !statusUrl || !retained.status || !RECOVERABLE_QUICK_FORECAST_STATUSES.has(retained.status)) return null;
  return {
    ...emptyQuickForecast,
    status: "recovering_existing_job",
    jobId,
    expectedRunId,
    statusUrl,
    committedRunId: UUID.test(String(retained.committedRunId ?? "")) ? retained.committedRunId! : null,
    progress: typeof retained.progress === "string" ? retained.progress.slice(0, 160) : null,
  };
}

export default function OperationalForecastWorkflow({
  initialSource = "newer",
  entryIntent = "resume",
}: {
  initialSource?: "assessed" | "newer";
  entryIntent?: "resume" | "new_assessed" | "new_upload";
}) {
  const [step, setStep] = useState<OperationalForecastStep>("upload_latest_data");
  const [sourceMode, setSourceMode] = useState<"assessed" | "newer">(initialSource);
  const [assignment, setAssignment] = useState<CurrentModelAssignmentResultSuccess | null>(null);
  const [assignmentState, setAssignmentState] = useState<"loading" | "ready" | "failed">("loading");
  const [files, setFiles] = useState<Partial<Record<"dengue" | "climate", LocalFilePreview>>>({});
  const [validationState, setValidationState] = useState<ServerValidationState>({ status: "idle" });
  const [validation, setValidation] = useState<QuickValidationReadyEvidence | null>(null);
  const [quickForecast, setQuickForecast] = useState<QuickForecastWorkflowState>(emptyQuickForecast);
  const [error, setError] = useState<string | null>(null);
  const validating = useRef(false);

  const readAssignment = useCallback(async () => {
    setAssignmentState("loading");
    const current = await getCurrentModelAssignment();
    if (!current.ok) {
      setAssignment(null);
      setAssignmentState("failed");
      setError(current.error.message.slice(0, 500));
      return null;
    }
    setAssignment(current);
    setAssignmentState("ready");
    setError(null);
    return current;
  }, []);

  useEffect(() => {
    let active = true;
    const recover = async () => {
      const current = await readAssignment();
      if (!active || !current) return;
      if (entryIntent !== "resume") {
        localStorage.removeItem(STORAGE_KEY);
        window.history.replaceState(window.history.state, "", "/forecast/run");
        return;
      }
      let retained: RetainedOperationalWorkflow = {};
      try {
        retained = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as RetainedOperationalWorkflow;
      } catch {
        localStorage.removeItem(STORAGE_KEY);
      }
      const recoveredValidation = boundedValidation(retained.validation);
      const recoveredForecast = boundedQuickForecast(retained.quickForecast);
      const matches = recoveredValidation
        && recoveredForecast
        && recoveredValidation.assignmentId === current.assignmentId
        && recoveredValidation.assignmentPointerSha256 === current.assignmentPointerSha256
        && recoveredValidation.selectedCandidateId === current.selectedCandidateId;
      if (!matches) {
        localStorage.removeItem(STORAGE_KEY);
        return;
      }
      setValidation(recoveredValidation);
      setQuickForecast(recoveredForecast);
      setStep(recoveredForecast.committedRunId ? "current_verification" : "forecast");
    };
    void recover();
    return () => {
      active = false;
    };
  }, [entryIntent, readAssignment]);

  const resetValidation = (nextFiles = files) => {
    setFiles(nextFiles);
    setValidationState({ status: "idle" });
    setValidation(null);
    setQuickForecast(emptyQuickForecast);
    setError(null);
    localStorage.removeItem(STORAGE_KEY);
  };

  const setFile = (preview: LocalFilePreview) => {
    const next = { ...files, [preview.key]: preview };
    resetValidation(next);
  };

  const removeFile = (key: "dengue" | "climate") => {
    const next = { ...files };
    delete next[key];
    resetValidation(next);
  };

  const acceptValidation = async (response: RuntimeValidationResponseSuccess, currentAssignment: CurrentModelAssignmentResultSuccess) => {
    const authority = response.activeModelAuthority;
    const bound = response.status === "ready"
      && response.workflowMode === "quick_forecast"
      && response.deploymentId === "dhaka_south"
      && response.eligibility.quickForecast.eligible
      && authority?.authoritySource === "committed_assignment"
      && authority.assignmentId === currentAssignment.assignmentId
      && authority.authoritySnapshotSha256 === currentAssignment.assignmentPointerSha256
      && authority.modelId === currentAssignment.selectedCandidateId;
    if (!bound || !authority) {
      setValidationState({ status: response.status, response });
      setValidation(null);
      setStep("validation");
      setError("The validation evidence did not match the verified current assignment. Review the refreshed authority before validating again.");
      await readAssignment();
      return;
    }
    const evidence: QuickValidationReadyEvidence = {
      workspaceId: response.workspaceId,
      datasetId: response.datasetId,
      deploymentId: "dhaka_south",
      validationRecordSha256: response.validationRecordSha256,
      workflowMode: "quick_forecast",
      assignmentId: authority.assignmentId,
      assignmentPointerSha256: authority.authoritySnapshotSha256,
      selectedCandidateId: authority.modelId,
    };
    setValidationState({ status: "ready", response });
    setValidation(evidence);
    setQuickForecast(emptyQuickForecast);
    setStep("forecast");
  };

  const validate = async () => {
    if (validating.current || !assignment || !files.dengue || !files.climate) return;
    validating.current = true;
    setValidationState({ status: "submitting" });
    setError(null);
    try {
      const response = await validateRuntimeDatasets({
        dengueFile: files.dengue.file,
        climateFile: files.climate.file,
        deploymentId: "dhaka_south",
        workflowMode: "quick_forecast",
      });
      if (!response.ok) throw new Error(response.error.message);
      await acceptValidation(response, assignment);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message.slice(0, 500) : "Operational forecast validation failed.";
      setValidationState({ status: "failed", error: { code: "validation_request_failed", category: "internal", message, retryable: true, correlationId: "not-available" } });
      setError(message);
    } finally {
      validating.current = false;
    }
  };

  const validateAssessmentSource = async () => {
    if (validating.current || !assignment) return;
    validating.current = true;
    setStep("validation");
    setValidationState({ status: "submitting" });
    setError(null);
    try {
      const response = await validateAssessedDataset();
      if (!response.ok) {
        setValidationState({ status: "failed", error: response.error });
        setError(response.error.message);
        return;
      }
      await acceptValidation(response, assignment);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message.slice(0, 500) : "Assessment dataset cannot be reused for the current operational forecast.";
      setValidationState({ status: "failed", error: { code: "assessment_dataset_handoff_failed", category: "validation", message, retryable: true, correlationId: "not-available" } });
      setError(message);
    } finally {
      validating.current = false;
    }
  };

  const updateQuickForecast = (next: QuickForecastWorkflowState) => {
    setQuickForecast(next);
    if (validation && next.jobId) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ validation, quickForecast: next } satisfies RetainedOperationalWorkflow));
    }
    if (next.status === "current_verified") setStep("complete");
    else if (["committed_pending_current_verification", "current_verification_pending", "current_verification_timeout"].includes(next.status)) setStep("current_verification");
    else setStep("forecast");
  };

  const completedThrough: OperationalForecastStep | null =
    step === "complete" ? "complete"
      : step === "current_verification" ? "forecast"
        : validation ? "validation"
          : step === "validation" ? "upload_latest_data"
            : null;
  const activeState = error ? "failed"
    : assignmentState === "loading" || validationState.status === "submitting"
      || ["starting", "queued", "running", "recovering_existing_job", "committed_pending_current_verification", "current_verification_pending"].includes(quickForecast.status)
      ? "busy"
      : quickForecast.status === "assignment_conflict" || quickForecast.status === "publication_in_progress"
        ? "conflict"
        : "idle";

  return <div className="space-y-6">
    <ForecastRunStepper workflow="operational" current={step} completedThrough={completedThrough} activeState={activeState} />
    {assignmentState === "loading" ? <AsyncStatusIndicator label="Verifying current model authority" delayedAfterSeconds={10} /> : null}
    {assignmentState === "failed" ? <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4" role="alert"><p className="font-semibold text-ink">Current assignment unavailable</p><p className="mt-1 text-sm text-ink-muted">{error}</p><Button className="mt-3" variant="secondary" onClick={() => void readAssignment()}>Check assignment status</Button></div> : null}
    {assignment ? <section className="rounded-xl border border-border-subtle bg-surface p-5"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-accent">Current governed model</p><h2 className="mt-1 font-semibold text-ink">{modelLabel(assignment.selectedCandidateId)}</h2></div><StatusBadge label="Assignment verified" variant="success" /></div><p className="mt-2 text-sm text-ink-muted">Forecast execution resolves this identity from server authority. The browser does not submit a model or candidate.</p><details className="mt-3"><summary className="cursor-pointer text-xs font-semibold text-accent outline-none focus-visible:ring-2 focus-visible:ring-focus">Technical assignment evidence</summary><dl className="mt-2 space-y-1 text-xs text-ink-muted"><div><dt className="inline font-medium text-ink">Assignment ID: </dt><dd className="inline break-all font-mono">{assignment.assignmentId}</dd></div><div><dt className="inline font-medium text-ink">Candidate ID: </dt><dd className="inline font-mono">{assignment.selectedCandidateId}</dd></div></dl></details></section> : null}

    {assignment && (step === "upload_latest_data" || step === "validation") && sourceMode === "assessed" ? <div className="space-y-5 rounded-2xl border border-border-subtle bg-surface p-5 shadow-sm sm:p-7">
      <div><p className="text-xs font-semibold uppercase tracking-wide text-accent">Data source</p><h2 className="mt-1 font-semibold text-ink">Using the validated dataset from the completed model assessment</h2><p className="mt-2 text-sm text-ink-muted">A new operational workspace will be created and validated against the current governed assignment.</p></div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2"><div className="rounded-lg border border-border-subtle bg-surface-muted p-4"><dt className="font-medium text-ink">Dengue data</dt><dd className="mt-1 text-ink-muted">Verified assessment dataset</dd></div><div className="rounded-lg border border-border-subtle bg-surface-muted p-4"><dt className="font-medium text-ink">Climate data</dt><dd className="mt-1 text-ink-muted">Verified assessment dataset</dd></div></dl>
      {validationState.status === "submitting" ? <AsyncStatusIndicator label="Validating assessed dataset for operational forecasting" detail="The server is creating a distinct operational workspace and revalidating it against the current assignment." delayedAfterSeconds={10} /> : null}
      {validationState.status === "failed" ? <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4" role="alert"><p className="font-semibold text-ink">{assessedDatasetFailureHeading(validationState.error.code)}</p><p className="mt-1 text-sm text-ink-muted">{validationState.error.message}</p><p className="mt-2 text-xs text-ink-muted">Assessment dataset cannot be reused for the current operational forecast.</p></div> : null}
      <div className="flex flex-wrap gap-3"><Button disabled={validationState.status === "submitting"} onClick={() => void validateAssessmentSource()}>{validationState.status === "submitting" ? "Validating assessed dataset…" : "Continue to operational validation"}</Button><Button variant="secondary" disabled={validationState.status === "submitting"} onClick={() => { resetValidation({}); setSourceMode("newer"); setStep("upload_latest_data"); }}>Use newer datasets instead</Button></div>
    </div> : null}

    {assignment && (step === "upload_latest_data" || step === "validation") && sourceMode === "newer" ? <div className="space-y-5 rounded-2xl border border-border-subtle bg-surface p-5 shadow-sm sm:p-7">
      <div className="rounded-xl border border-warning/25 bg-warning/10 p-4 text-sm text-ink-muted">Select both latest datasets to create a new operational forecast workspace. Assessment workspaces and browser path strings are never reused.</div>
      <div className="grid gap-5 lg:grid-cols-2">
        <DatasetUploadPanel workflow="operational" kind="dengue" preview={files.dengue} onChange={setFile} onRemove={() => removeFile("dengue")} />
        <DatasetUploadPanel workflow="operational" kind="climate" preview={files.climate} onChange={setFile} onRemove={() => removeFile("climate")} />
      </div>
      {files.dengue && files.climate ? <DatasetValidationSummary files={files} mode="quick_forecast" serverValidation={validationState} onMode={() => undefined} onValidate={() => void validate()} revalidationRequired currentAssignment={assignment} validationActionLabel="Validate latest data for operational forecast" /> : null}
      {files.dengue && files.climate && step === "upload_latest_data" ? <div className="flex justify-end"><Button onClick={() => setStep("validation")}>Continue to validation</Button></div> : null}
    </div> : null}

    {assignment && validation && ["forecast", "current_verification", "complete"].includes(step) ? <QuickForecastRunPanel
      validation={validation}
      assignment={assignment}
      state={quickForecast}
      onStateChange={updateQuickForecast}
      onAssignmentConflict={() => {
        resetValidation({});
        setStep("upload_latest_data");
        void readAssignment();
      }}
      onRequireFreshValidation={() => {
        resetValidation(files);
        setStep("validation");
      }}
    /> : null}
  </div>;
}
