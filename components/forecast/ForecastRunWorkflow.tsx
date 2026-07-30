"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Button from "@/components/ui/Button";
import ApprovedForecastPanel from "./ApprovedForecastPanel";
import ApprovalPanel from "./ApprovalPanel";
import DatasetUploadPanel from "./DatasetUploadPanel";
import DatasetValidationSummary from "./DatasetValidationSummary";
import ForecastRunStepper from "./ForecastRunStepper";
import ModelAssignmentPanel from "./ModelAssignmentPanel";
import ModelSuitabilitySummary from "./ModelSuitabilitySummary";
import ProcessingState from "./ProcessingState";
import type {
  ApprovedForecastWorkflowState,
  ForecastWorkflowState,
  LocalFilePreview,
  ModelAssignmentWorkflowState,
  WorkflowStep,
} from "@/lib/forecast-workflow-types";
import {
  getDatasetAssessment,
  getRuntimeJob,
  getRuntimeJobByStatusUrl,
  recordAssessmentDecision,
  startDatasetAssessment,
  validateRuntimeDatasets,
} from "@/lib/runtime/client";
import type {
  GovernedDecisionRequest,
  JobStatusResponse,
  RuntimeCandidateId,
} from "@/lib/runtime/contracts";
import { modelLabel } from "@/lib/status-labels";

const STORAGE_KEY = "dengueops-model-assessment-workflow-v1";
const ASSESSMENT_COMPLETED = "assessment_completed";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const RUNTIME_CANDIDATE_IDS = new Set<RuntimeCandidateId>([
  "moving_average_4w",
  "seasonal_naive_52w",
  "ridge_regression",
  "poisson_regression",
  "random_forest",
  "gradient_boosting",
  "elastic_net",
  "negative_binomial_regression",
  "extra_trees",
  "hist_gradient_boosting",
  "poisson_gam",
  "previous_week_naive",
]);

const emptyApprovedForecast: ApprovedForecastWorkflowState = {
  status: "idle",
  jobId: null,
  statusUrl: null,
  runId: null,
  committedRunId: null,
  approvedForecastCommitSha256: null,
  sourceDecisionId: null,
  selectedModelId: null,
  progress: null,
  error: null,
};

const emptyAssignment: ModelAssignmentWorkflowState = {
  status: "loading_current_assignment",
  current: null,
  approvedJobVerified: false,
  expectedAssignmentPointerSha256: null,
  errorCode: null,
  error: null,
};

const initial: ForecastWorkflowState = {
  step: "upload",
  files: {},
  mode: "assess_dataset",
  validatedWorkflowMode: null,
  workflowRevalidationRequired: false,
  processingStatus: "idle",
  serverValidation: { status: "idle" },
  workspaceId: null,
  datasetId: null,
  retainedAssessmentId: null,
  assessmentJobId: null,
  job: null,
  assessment: null,
  approval: null,
  approvedForecast: emptyApprovedForecast,
  assignment: emptyAssignment,
  result: null,
  error: null,
};

interface RetainedWorkflow {
  assessmentId?: string;
  assessmentJobId?: string;
  decisionId?: string;
  approvedForecast?: Partial<ApprovedForecastWorkflowState>;
  assignment?: Partial<ModelAssignmentWorkflowState>;
}

const completedThrough = (state: ForecastWorkflowState): WorkflowStep | null => {
  if (state.step === "complete") return "complete";
  if (state.assignment.status === "assigned_verified") return "assignment";
  if (state.approvedForecast.status === "completed") return "qualification_run";
  if (state.approval || state.assessment?.workflow.decision) return "decision";
  if (state.step === "decision") return "ranking";
  if (state.assessment) return "assessment";
  if (state.step === "assessment") return "validation";
  if (state.serverValidation.status === "ready") return "validation";
  if (state.step === "validation") return "upload";
  return null;
};

function boundedRetainedForecast(value: unknown): ApprovedForecastWorkflowState {
  if (!value || typeof value !== "object") return emptyApprovedForecast;
  const candidate = value as Partial<ApprovedForecastWorkflowState>;
  const status = candidate.status;
  if (!status || !["idle", "queued", "running", "committing", "completed", "failed", "timed_out", "cancelled"].includes(status)) return emptyApprovedForecast;
  const validId = (id: unknown) => typeof id === "string" && UUID.test(id);
  const validSha = (hash: unknown) => typeof hash === "string" && SHA.test(hash);
  const validCandidateId = (modelId: unknown): modelId is RuntimeCandidateId =>
    typeof modelId === "string" && RUNTIME_CANDIDATE_IDS.has(modelId as RuntimeCandidateId);
  return {
    status,
    jobId: validId(candidate.jobId) ? candidate.jobId! : null,
    statusUrl: validId(candidate.jobId) ? `/api/runtime/jobs/${candidate.jobId}` : null,
    runId: validId(candidate.runId) ? candidate.runId! : null,
    committedRunId: validId(candidate.committedRunId) ? candidate.committedRunId! : null,
    approvedForecastCommitSha256: validSha(candidate.approvedForecastCommitSha256) ? candidate.approvedForecastCommitSha256! : null,
    sourceDecisionId: validId(candidate.sourceDecisionId) ? candidate.sourceDecisionId! : null,
    selectedModelId: validCandidateId(candidate.selectedModelId) ? candidate.selectedModelId : null,
    progress: typeof candidate.progress === "string" ? candidate.progress.slice(0, 160) : null,
    error: typeof candidate.error === "string" ? candidate.error.slice(0, 500) : null,
  };
}

function boundedRetainedAssignment(value: unknown): ModelAssignmentWorkflowState {
  if (!value || typeof value !== "object") return emptyAssignment;
  const candidate = value as Partial<ModelAssignmentWorkflowState>;
  const current = candidate.current;
  const validCandidateId = (modelId: unknown): modelId is RuntimeCandidateId =>
    typeof modelId === "string" && RUNTIME_CANDIDATE_IDS.has(modelId as RuntimeCandidateId);
  const boundedCurrent = current
    && current.ok === true
    && current.status === "assigned"
    && typeof current.assignmentId === "string"
    && UUID.test(current.assignmentId)
    && validCandidateId(current.selectedCandidateId)
    && typeof current.selectedCandidateLabel === "string"
    && current.selectedCandidateLabel.length <= 160
    && SHA.test(current.assignmentCommitSha256)
    && SHA.test(current.assignmentPointerSha256)
    && UUID.test(current.sourceApprovedForecastRunId)
    && typeof current.createdAt === "string"
    ? current
    : null;
  return {
    status: "loading_current_assignment",
    current: boundedCurrent,
    approvedJobVerified: false,
    expectedAssignmentPointerSha256: boundedCurrent?.assignmentPointerSha256 ?? null,
    errorCode: null,
    error: null,
  };
}

export default function ForecastRunWorkflow() {
  const [state, setState] = useState<ForecastWorkflowState>(initial);
  const mounted = useRef(true);
  const assessmentAction = useRef(false);
  const decisionAction = useRef(false);
  const recoveryStarted = useRef(false);
  const recordedDecision = state.approval ?? state.assessment?.workflow.decision ?? null;
  const decisionPolicyAvailable = Boolean(state.assessment && ["phase1_decision_policy_available", "phase2_decision_policy_available"].includes(String(state.assessment.workflow.decisionCompatibilityStatus)));

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const persist = (next: ForecastWorkflowState) => {
    const retained: RetainedWorkflow = {
      assessmentId: next.retainedAssessmentId ?? undefined,
      assessmentJobId: next.assessmentJobId ?? undefined,
      decisionId: (next.approval ?? next.assessment?.workflow.decision)?.decisionId,
      approvedForecast: next.approvedForecast,
      assignment: next.assignment,
    };
    if (retained.assessmentId || retained.assessmentJobId || retained.decisionId || retained.approvedForecast?.jobId) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(retained));
    }
  };

  const update = (updater: (current: ForecastWorkflowState) => ForecastWorkflowState) => {
    setState((current) => {
      const next = updater(current);
      persist(next);
      return next;
    });
  };

  const loadCommittedAssessment = async (assessmentId: string) => {
    const assessment = await getDatasetAssessment(assessmentId);
    if (!assessment.ok) throw new Error(assessment.error.message);
    if (!mounted.current) return;
    update((current) => ({
      ...current,
      retainedAssessmentId: assessment.assessmentId,
      assessment,
      processingStatus: "completed",
      job: current.job?.ok ? { ...current.job, progress: ASSESSMENT_COMPLETED } as JobStatusResponse : current.job,
      step: current.assignment.status === "assigned_verified"
        ? "complete"
        : current.approvedForecast.status === "completed"
          ? "assignment"
          : assessment.workflow.decision
            ? "qualification_run"
            : "ranking",
      error: null,
    }));
  };

  const pollAssessment = async (jobId: string, assessmentId: string, statusUrl?: string) => {
    if (assessmentAction.current) return;
    assessmentAction.current = true;
    let delay = 1500;
    try {
      while (mounted.current) {
        const job = statusUrl ? await getRuntimeJobByStatusUrl(statusUrl) : await getRuntimeJob(jobId);
        if (!job.ok) throw new Error(job.error.message);
        if (job.jobKind !== "dataset_assessment" || job.jobId !== jobId || job.assessmentId !== assessmentId) throw new Error("The assessment job did not match the retained workspace evidence.");
        update((current) => ({ ...current, job, processingStatus: job.status, error: null }));
        if (job.status === "completed") {
          if (job.committedAssessmentId !== assessmentId) throw new Error("The assessment completed without the expected committed identity.");
          await loadCommittedAssessment(assessmentId);
          return;
        }
        if (job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") throw new Error(job.error?.message ?? `The assessment ended with ${job.status}.`);
        await new Promise((resolve) => window.setTimeout(resolve, delay));
        delay = Math.min(8000, Math.round(delay * 1.35));
      }
    } catch (reason) {
      if (mounted.current) update((current) => ({ ...current, processingStatus: "failed", error: reason instanceof Error ? reason.message.slice(0, 500) : "Assessment verification failed." }));
    } finally {
      assessmentAction.current = false;
    }
  };

  const checkAssessmentStatus = async () => {
    if (!state.assessmentJobId || !state.retainedAssessmentId) return;
    try {
      const job = await getRuntimeJob(state.assessmentJobId);
      if (!job.ok) throw new Error(job.error.message);
      if (job.jobKind !== "dataset_assessment" || job.jobId !== state.assessmentJobId || job.assessmentId !== state.retainedAssessmentId) {
        throw new Error("The assessment job did not match the retained workspace evidence.");
      }
      update((current) => ({ ...current, job, processingStatus: job.status, error: null }));
      if (job.status === "completed") {
        if (job.committedAssessmentId !== state.retainedAssessmentId) throw new Error("The assessment completed without the expected committed identity.");
        await loadCommittedAssessment(state.retainedAssessmentId);
      }
    } catch (reason) {
      update((current) => ({ ...current, error: reason instanceof Error ? reason.message.slice(0, 500) : "Assessment status could not be verified." }));
    }
  };

  useEffect(() => {
    if (recoveryStarted.current) return;
    recoveryStarted.current = true;
    let retained: RetainedWorkflow = {};
    try {
      retained = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}") as RetainedWorkflow;
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
    const assessmentId = typeof retained.assessmentId === "string" && UUID.test(retained.assessmentId) ? retained.assessmentId : null;
    const assessmentJobId = typeof retained.assessmentJobId === "string" && UUID.test(retained.assessmentJobId) ? retained.assessmentJobId : null;
    const approvedForecast = boundedRetainedForecast(retained.approvedForecast);
    const assignment = boundedRetainedAssignment(retained.assignment);
    if (!assessmentId) return;
    update((current) => ({ ...current, retainedAssessmentId: assessmentId, assessmentJobId, approvedForecast, assignment, step: "assessment", processingStatus: assessmentJobId ? "queued" : "idle" }));
    void loadCommittedAssessment(assessmentId).catch(() => {
      if (assessmentJobId) void pollAssessment(assessmentJobId, assessmentId);
      else if (mounted.current) update((current) => ({ ...current, error: "The retained assessment could not be verified. No decision or forecast was restarted." }));
    });
    // Recovery runs once and never publishes or consumes an append-only action.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setFile = (preview: LocalFilePreview) => update((current) => ({
    ...current,
    files: { ...current.files, [preview.key]: preview },
    serverValidation: { status: "idle" },
    validatedWorkflowMode: null,
    workspaceId: null,
    datasetId: null,
    error: null,
  }));

  const removeFile = (key: "dengue" | "climate") => update((current) => {
    const files = { ...current.files };
    delete files[key];
    return { ...current, files, serverValidation: { status: "idle" }, validatedWorkflowMode: null, workspaceId: null, datasetId: null, error: null };
  });

  const validate = async () => {
    if (!state.files.dengue || !state.files.climate || state.processingStatus === "validating") return;
    update((current) => ({ ...current, processingStatus: "validating", serverValidation: { status: "submitting" }, error: null }));
    try {
      const response = await validateRuntimeDatasets({
        dengueFile: state.files.dengue.file,
        climateFile: state.files.climate.file,
        deploymentId: "dhaka_south",
        workflowMode: "assess_dataset",
      });
      if (!response.ok) throw new Error(response.error.message);
      update((current) => ({
        ...current,
        serverValidation: { status: response.status, response },
        validatedWorkflowMode: response.status === "ready" ? "assess_dataset" : null,
        workspaceId: response.workspaceId,
        datasetId: response.datasetId,
        processingStatus: response.status === "ready" ? "ready" : "blocked",
        error: null,
      }));
    } catch (reason) {
      update((current) => ({ ...current, processingStatus: "failed", serverValidation: { status: "failed", error: { code: "validation_request_failed", category: "internal", message: reason instanceof Error ? reason.message.slice(0, 500) : "Validation failed.", retryable: true, correlationId: "not-available" } } }));
    }
  };

  const runAssessment = async () => {
    const validation = state.serverValidation.status === "ready" ? state.serverValidation.response : null;
    if (assessmentAction.current || !validation || !state.workspaceId || !state.datasetId || validation.eligibility.assessDataset.assessmentStatus !== "full_assessment_eligible") return;
    assessmentAction.current = true;
    update((current) => ({ ...current, processingStatus: "queued", error: null }));
    try {
      const started = await startDatasetAssessment({ workspaceId: state.workspaceId, datasetId: state.datasetId, deploymentId: validation.deploymentId, validationRecordSha256: validation.validationRecordSha256 });
      if (!started.ok) throw new Error(started.error.message);
      update((current) => ({ ...current, retainedAssessmentId: started.assessmentId, assessmentJobId: started.jobId, processingStatus: "queued" }));
      assessmentAction.current = false;
      await pollAssessment(started.jobId, started.assessmentId, started.statusUrl);
    } catch (reason) {
      assessmentAction.current = false;
      update((current) => ({ ...current, processingStatus: "failed", error: reason instanceof Error ? reason.message.slice(0, 500) : "The assessment could not be started." }));
    }
  };

  const recordDecision = async (request: GovernedDecisionRequest) => {
    if (!state.assessment || recordedDecision || decisionAction.current) return;
    decisionAction.current = true;
    update((current) => ({ ...current, processingStatus: "queued", error: null }));
    try {
      const response = await recordAssessmentDecision(state.assessment.assessmentId, request);
      if (!response.ok) throw new Error(response.error.message);
      update((current) => ({ ...current, approval: response, processingStatus: "completed", step: "qualification_run", error: null }));
    } catch (reason) {
      update((current) => ({ ...current, processingStatus: "failed", error: reason instanceof Error ? reason.message.slice(0, 500) : "The governed model decision could not be recorded." }));
    } finally {
      decisionAction.current = false;
    }
  };

  const assessmentReady = state.serverValidation.status === "ready"
    && state.validatedWorkflowMode === "assess_dataset"
    && state.serverValidation.response.eligibility.assessDataset.assessmentStatus === "full_assessment_eligible";
  const approvedState = useMemo(() => state.approvedForecast, [state.approvedForecast]);
  const assessmentCandidateCount = state.serverValidation.status === "ready"
    && state.serverValidation.response.workflowMode === "assess_dataset"
    && state.serverValidation.response.eligibility.assessDataset.candidateSetStatus === "complete_candidate_set"
    ? Object.keys(state.serverValidation.response.eligibility.assessDataset.candidateEligibility).length
    : undefined;
  const approvedEvidenceReady = Boolean(
    recordedDecision
    && approvedState.status === "completed"
    && approvedState.jobId
    && approvedState.runId
    && approvedState.committedRunId
    && approvedState.runId === approvedState.committedRunId
    && approvedState.approvedForecastCommitSha256
    && approvedState.sourceDecisionId === recordedDecision.decisionId
    && approvedState.selectedModelId
    && approvedState.selectedModelId === recordedDecision.selectedModelId,
  );
  const selectedCandidateLabel = recordedDecision?.selectedModelId
    ? modelLabel(recordedDecision.selectedModelId)
    : "Server-resolved candidate";

  useEffect(() => {
    if (!approvedEvidenceReady || state.step !== "qualification_run") return;
    update((current) => ({ ...current, step: "assignment", processingStatus: "completed", error: null }));
    // Transition only after retained approved-run identities reconcile.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [approvedEvidenceReady, state.step]);

  const activeStepState = state.error
    ? "failed"
    : state.assignment.status === "pointer_conflict" || state.assignment.status === "publication_in_progress"
      ? "conflict"
      : ["validating", "queued", "running", "committing"].includes(state.processingStatus)
        || state.assignment.status === "loading_current_assignment"
        || state.assignment.status === "publishing"
        ? "busy"
        : "idle";

  return <div className="space-y-6">
    <ForecastRunStepper current={state.step} completedThrough={completedThrough(state)} activeState={activeStepState} />
    {state.error && state.step !== "decision" ? <div className="rounded-xl border border-destructive/25 bg-destructive/10 p-4 text-sm text-destructive" role="alert">{state.error}</div> : null}
    <div className="rounded-2xl border border-border-subtle bg-surface p-5 shadow-sm sm:p-7">
      {state.step === "upload" ? <div className="space-y-5">
        <div className="grid gap-5 lg:grid-cols-2">
          <DatasetUploadPanel kind="dengue" preview={state.files.dengue} onChange={setFile} onRemove={() => removeFile("dengue")} />
          <DatasetUploadPanel kind="climate" preview={state.files.climate} onChange={setFile} onRemove={() => removeFile("climate")} />
        </div>
        <div className="flex justify-end"><Button disabled={!state.files.dengue || !state.files.climate} onClick={() => update((current) => ({ ...current, step: "validation" }))}>Continue to validation</Button></div>
      </div> : null}

      {state.step === "validation" ? <div className="space-y-5">
        <DatasetValidationSummary files={state.files} mode="assess_dataset" serverValidation={state.serverValidation} onMode={() => undefined} onValidate={() => void validate()} revalidationRequired={false} />
        <div className="flex justify-between gap-3"><Button variant="secondary" onClick={() => update((current) => ({ ...current, step: "upload" }))}>Back</Button><Button disabled={!assessmentReady} onClick={() => update((current) => ({ ...current, step: "assessment" }))}>Continue to assessment</Button></div>
      </div> : null}

      {state.step === "assessment" ? <div className="space-y-5">
        <div className="rounded-xl border border-border-subtle bg-surface-muted p-5"><h2 className="font-semibold text-ink">Governed assessment</h2><p className="mt-2 text-sm text-ink-muted">The validated workspace will evaluate the complete candidate set under its immutable common fold plan. No forecast or assignment starts here.</p></div>
        {["queued", "running", "committing"].includes(state.processingStatus) ? <ProcessingState status={state.processingStatus} stage={state.job?.ok ? state.job.progress : undefined} workflow="assess_dataset" candidateCount={assessmentCandidateCount} onCheckStatus={() => void checkAssessmentStatus()} /> : null}
        {!state.retainedAssessmentId ? <Button disabled={!assessmentReady || assessmentAction.current} onClick={() => void runAssessment()}>Start governed assessment</Button> : null}
      </div> : null}

      {state.step === "ranking" ? <div className="space-y-5">
        <ModelSuitabilitySummary assessment={state.assessment} />
        <div className="flex justify-end"><Button disabled={!state.assessment?.technicalWinnerModelId || !decisionPolicyAvailable} onClick={() => update((current) => ({ ...current, step: "decision" }))}>Review governed decision</Button></div>
      </div> : null}

      {state.step === "decision" && state.assessment ? <div className="space-y-5">
        <ModelSuitabilitySummary assessment={state.assessment} />
        <ApprovalPanel assessment={state.assessment} decision={recordedDecision} busy={decisionAction.current || state.processingStatus === "queued"} error={state.error} onGovernedDecision={(request) => void recordDecision(request)} />
      </div> : null}

      {state.step === "qualification_run" && state.assessment && recordedDecision ? <div className="space-y-5">
        <ModelSuitabilitySummary assessment={state.assessment} />
        <ApprovalPanel assessment={state.assessment} decision={recordedDecision} busy error={null} />
        <ApprovedForecastPanel decision={recordedDecision} state={approvedState} onStateChange={(approvedForecast) => update((current) => ({ ...current, approvedForecast, step: approvedForecast.status === "completed" ? "assignment" : current.step, processingStatus: approvedForecast.status === "idle" ? current.processingStatus : approvedForecast.status }))} />
      </div> : null}

      {state.step === "assignment" && approvedEvidenceReady ? <div className="space-y-5">
        <ModelSuitabilitySummary assessment={state.assessment} />
        <ModelAssignmentPanel
          approvedForecast={approvedState}
          selectedCandidateLabel={selectedCandidateLabel}
          state={state.assignment}
          onStateChange={(assignment) => update((current) => ({
            ...current,
            assignment,
            step: assignment.status === "assigned_verified" && assignment.current ? "complete" : current.step,
            processingStatus: assignment.status === "assigned_verified" ? "completed" : current.processingStatus,
            error: null,
          }))}
        />
      </div> : null}

      {state.step === "complete" && state.assignment.status === "assigned_verified" && state.assignment.current ? <div className="rounded-xl border border-success/25 bg-success/10 p-6" role="status">
        <h2 className="text-xl font-semibold text-ink">Model assessment and assignment complete</h2>
        <p className="mt-2 text-sm text-ink-muted">The governed assignment for {modelLabel(state.assignment.current.selectedCandidateId)} is verified as current. No operational forecast was started.</p>
        <Link href="/forecast/run" className="mt-4 inline-flex rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white outline-none focus-visible:ring-2 focus-visible:ring-focus">Run Forecast</Link>
        <details className="mt-4"><summary className="cursor-pointer text-xs font-semibold text-accent outline-none focus-visible:ring-2 focus-visible:ring-focus">Technical assignment evidence</summary><dl className="mt-2 space-y-1 text-xs text-ink-muted"><div><dt className="inline font-medium text-ink">Assignment ID: </dt><dd className="inline break-all font-mono">{state.assignment.current.assignmentId}</dd></div><div><dt className="inline font-medium text-ink">Assignment pointer SHA-256: </dt><dd className="inline break-all font-mono">{state.assignment.current.assignmentPointerSha256}</dd></div></dl></details>
      </div> : null}
    </div>
  </div>;
}
