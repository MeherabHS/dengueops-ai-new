"use client";

import { useEffect, useReducer, useRef } from "react";
import Button from "@/components/ui/Button";
import ForecastRunStepper from "./ForecastRunStepper";
import DatasetUploadPanel from "./DatasetUploadPanel";
import DatasetValidationSummary from "./DatasetValidationSummary";
import WorkflowChoice from "./WorkflowChoice";
import ApprovalPanel from "./ApprovalPanel";
import ProcessingState from "./ProcessingState";
import ForecastResultSummary from "./ForecastResultSummary";
import ModelSuitabilitySummary from "./ModelSuitabilitySummary";
import type { ForecastWorkflowState, LocalFilePreview, WorkflowMode, WorkflowStep } from "@/lib/forecast-workflow-types";
import { getDatasetAssessment, getLatestDashboard, getRuntimeJob, recordAssessmentDecision, startApprovedForecast, startDatasetAssessment, startQuickForecast, validateRuntimeDatasets } from "@/lib/runtime/client";
import type { DatasetAssessmentResultSuccess, DecisionChoice, DecisionResultSuccess, JobStatusResponse, RuntimeErrorResponse, RuntimeValidationResponseSuccess } from "@/lib/runtime/contracts";

type Action =
  | { type: "file"; preview: LocalFilePreview }
  | { type: "remove"; key: "dengue" | "climate" }
  | { type: "mode"; mode: WorkflowMode }
  | { type: "step"; step: WorkflowStep }
  | { type: "validation_submitting" }
  | { type: "validation_response"; response: RuntimeValidationResponseSuccess }
  | { type: "validation_failed"; error: RuntimeErrorResponse["error"] }
  | { type: "job_queued" }
  | { type: "job_status"; response: JobStatusResponse }
  | { type: "job_failed"; message: string; status?: "failed" | "timed_out" | "cancelled" }
  | { type: "job_completed"; runId: string; point: number; targetPeriod: string; approved?: boolean }
  | { type: "assessment_completed"; assessment: DatasetAssessmentResultSuccess }
  | { type: "decision_recorded"; decision: DecisionResultSuccess };

const initial: ForecastWorkflowState = {
  step: "upload",
  files: {},
  mode: null,
  processingStatus: "idle",
  serverValidation: { status: "idle" },
  workspaceId: null,
  datasetId: null,
  job: null,
  assessment: null,
  approval: null,
  result: null,
};

function resetValidation(state: ForecastWorkflowState): ForecastWorkflowState {
  return { ...state, serverValidation: { status: "idle" }, workspaceId: null, datasetId: null, job: null, result: null, assessment: null, approval: null, processingStatus: "idle" };
}

function reducer(state: ForecastWorkflowState, action: Action): ForecastWorkflowState {
  switch (action.type) {
    case "file":
      return resetValidation({ ...state, files: { ...state.files, [action.preview.key]: action.preview } });
    case "remove": {
      const files = { ...state.files };
      delete files[action.key];
      return resetValidation({ ...state, files });
    }
    case "mode":
      return state.mode === action.mode ? state : resetValidation({ ...state, mode: action.mode });
    case "step":
      return { ...state, step: action.step };
    case "validation_submitting":
      return { ...state, processingStatus: "validating", serverValidation: { status: "submitting" } };
    case "validation_response":
      return {
        ...state,
        processingStatus: action.response.status === "ready" ? "ready" : "blocked",
        serverValidation: { status: action.response.status, response: action.response },
        workspaceId: action.response.workspaceId,
        datasetId: action.response.datasetId,
      };
    case "validation_failed":
      return { ...state, processingStatus: "failed", serverValidation: { status: "failed", error: action.error }, workspaceId: null, datasetId: null };
    case "job_queued":
      return { ...state, processingStatus: "queued" };
    case "job_status":
      return action.response.ok ? { ...state, job: action.response, processingStatus: action.response.status } : state;
    case "job_failed":
      return { ...state, processingStatus: action.status ?? "failed", result: state.mode === "quick_forecast" ? { runId: state.job?.ok && state.job.jobKind === "quick_forecast" ? state.job.runId : "not-committed", status: "failed", error: action.message } : null };
    case "job_completed":
      return { ...state, step: "results", processingStatus: "completed", result: { runId: action.runId, status: "completed", forecast: { point: action.point, lower: null, upper: null, targetPeriod: action.targetPeriod }, uncertaintyStatus: action.approved ? "pending_selected_model_calibration" : "pending_dataset_specific_calibration", preparednessStatus: "unavailable_missing_planning_policy" } };
    case "assessment_completed":
      return { ...state, step: "results", processingStatus: "completed", assessment: action.assessment, result: null };
    case "decision_recorded":
      return { ...state, processingStatus: "completed", approval: action.decision };
  }
}

const order: WorkflowStep[] = ["upload", "validate", "choose", "review", "results"];

export default function ForecastRunWorkflow() {
  const [state, dispatch] = useReducer(reducer, initial);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);
  const index = order.indexOf(state.step);
  const both = Boolean(state.files.dengue && state.files.climate);
  const response = state.serverValidation.status === "ready" || state.serverValidation.status === "invalid"
    ? state.serverValidation.response
    : null;
  const selectedEligible = state.mode === "quick_forecast"
    ? response?.eligibility.quickForecast.eligible
    : state.mode === "assess_dataset"
      ? response?.eligibility.assessDataset.assessmentStatus === "full_assessment_eligible"
      : false;
  const canNext = state.step === "upload"
    ? both
    : state.step === "validate"
      ? Boolean(response?.status === "ready" && selectedEligible)
      : state.step === "choose"
        ? Boolean(state.mode && selectedEligible)
        : state.step !== "review";

  const validate = async () => {
    if (!state.files.dengue || !state.files.climate || !state.mode) return;
    dispatch({ type: "validation_submitting" });
    try {
      const result = await validateRuntimeDatasets({
        dengueFile: state.files.dengue.file,
        climateFile: state.files.climate.file,
        deploymentId: "dhaka_south",
        workflowMode: state.mode,
      });
      if (result.ok) dispatch({ type: "validation_response", response: result });
      else dispatch({ type: "validation_failed", error: result.error });
    } catch {
      dispatch({
        type: "validation_failed",
        error: {
          code: "validation_request_failed",
          category: "internal",
          message: "The validation service could not be reached.",
          retryable: true,
          correlationId: "not-available",
        },
      });
    }
  };

  const runQuickForecast = async () => {
    if (!response || !state.workspaceId || !state.datasetId || state.mode !== "quick_forecast" || !response.eligibility.quickForecast.eligible) return;
    let started;
    try { started = await startQuickForecast({ workspaceId: state.workspaceId, datasetId: state.datasetId, deploymentId: response.deploymentId, validationRecordSha256: response.validationRecordSha256 }); }
    catch { dispatch({ type: "job_failed", message: "The Quick Forecast job could not be queued." }); return; }
    if (!started.ok) { dispatch({ type: "job_failed", message: started.error.message }); return; }
    dispatch({ type: "job_queued" });
    let delay = 2000;
    while (mounted.current) {
      let job;
      try { job = await getRuntimeJob(started.jobId); }
      catch { dispatch({ type: "job_failed", message: "Runtime job status could not be refreshed." }); return; }
      if (!mounted.current) return;
      if (!job.ok) { dispatch({ type: "job_failed", message: job.error.message }); return; }
      dispatch({ type: "job_status", response: job });
      if (job.status === "completed") {
        if (job.jobKind !== "quick_forecast" || !job.committedRunId) { dispatch({ type: "job_failed", message: "The worker completed without a committed run identity." }); return; }
        let latest;
        try { latest = await getLatestDashboard(response.deploymentId); }
        catch { dispatch({ type: "job_failed", message: "The committed dashboard could not be refreshed; the previous Overview remains available." }); return; }
        if (!latest.ok || latest.runId !== job.committedRunId || latest.dashboard.latestRun.runId !== job.committedRunId) {
          dispatch({ type: "job_failed", message: latest.ok ? "The committed dashboard identity did not match the completed job." : latest.error.message }); return;
        }
        sessionStorage.setItem("dengueops-latest-dashboard", JSON.stringify({ runId: latest.runId, dashboard: latest.dashboard }));
        dispatch({ type: "job_completed", runId: latest.runId, point: latest.dashboard.forecastCases, targetPeriod: latest.dashboard.targetPeriod });
        window.location.assign("/dashboard");
        return;
      }
      if (job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") {
        dispatch({ type: "job_failed", status: job.status, message: job.error?.message ?? `The runtime job ended with status ${job.status}.` }); return;
      }
      await new Promise(resolve => window.setTimeout(resolve, delay));
      delay = Math.min(10000, Math.round(delay * 1.35));
    }
  };

  const runAssessment = async () => {
    if (!response || !state.workspaceId || !state.datasetId || state.mode !== "assess_dataset" || response.eligibility.assessDataset.assessmentStatus !== "full_assessment_eligible") return;
    let started;
    try { started = await startDatasetAssessment({ workspaceId: state.workspaceId, datasetId: state.datasetId, deploymentId: response.deploymentId, validationRecordSha256: response.validationRecordSha256 }); }
    catch { dispatch({ type: "job_failed", message: "The dataset-assessment job could not be queued." }); return; }
    if (!started.ok) { dispatch({ type: "job_failed", message: started.error.message }); return; }
    dispatch({ type: "job_queued" });
    let delay = 2000;
    while (mounted.current) {
      let job;
      try { job = await getRuntimeJob(started.jobId); }
      catch { dispatch({ type: "job_failed", message: "Assessment job status could not be refreshed." }); return; }
      if (!mounted.current) return;
      if (!job.ok) { dispatch({ type: "job_failed", message: job.error.message }); return; }
      dispatch({ type: "job_status", response: job });
      if (job.status === "completed") {
        if (job.jobKind !== "dataset_assessment" || job.assessmentId !== started.assessmentId || job.committedAssessmentId !== started.assessmentId) { dispatch({ type: "job_failed", message: "The worker completed without the expected committed assessment identity." }); return; }
        let assessment;
        try { assessment = await getDatasetAssessment(started.assessmentId); }
        catch { dispatch({ type: "job_failed", message: "The committed assessment could not be loaded." }); return; }
        if (!assessment.ok || assessment.assessmentId !== job.committedAssessmentId) { dispatch({ type: "job_failed", message: assessment.ok ? "The assessment result identity did not match the completed job." : assessment.error.message }); return; }
        dispatch({ type: "assessment_completed", assessment });
        return;
      }
      if (job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") { dispatch({ type: "job_failed", status: job.status, message: job.error?.message ?? `The assessment job ended with status ${job.status}.` }); return; }
      await new Promise(resolve => window.setTimeout(resolve, delay));
      delay = Math.min(10000, Math.round(delay * 1.35));
    }
  };

  const recordDecision = async (choice: DecisionChoice, reason: string) => {
    if (!state.assessment) return;
    dispatch({ type: "job_queued" });
    let result;
    try { result = await recordAssessmentDecision(state.assessment.assessmentId, { decision: choice, reason, expectedAssessmentSummarySha256: state.assessment.integrity.assessmentSummarySha256 }); }
    catch { dispatch({ type: "job_failed", message: "The trusted internal decision could not be recorded." }); return; }
    if (!result.ok) { dispatch({ type: "job_failed", message: result.error.message }); return; }
    dispatch({ type: "decision_recorded", decision: result });
  };

  const runApprovedForecast = async () => {
    if (!state.approval?.forecastAuthorized || state.approval.authorizationStatus !== "available") return;
    let started;
    try { started = await startApprovedForecast(state.approval.decisionId, { expectedDecisionCommitSha256: state.approval.decisionCommitSha256 }); }
    catch { dispatch({ type: "job_failed", message: "The approved forecast could not be queued." }); return; }
    if (!started.ok) { dispatch({ type: "job_failed", message: started.error.message }); return; }
    dispatch({ type: "job_queued" }); let delay=2000;
    while(mounted.current){let job;try{job=await getRuntimeJob(started.jobId);}catch{dispatch({type:"job_failed",message:"Approved forecast status could not be refreshed."});return;}if(!job.ok){dispatch({type:"job_failed",message:job.error.message});return;}dispatch({type:"job_status",response:job});if(job.status==="completed"){if(job.jobKind!=="approved_forecast"||job.decisionId!==state.approval.decisionId||job.committedRunId!==started.runId){dispatch({type:"job_failed",message:"The approved worker completed without the expected immutable run."});return;}let latest;try{latest=await getLatestDashboard("dhaka_south");}catch{dispatch({type:"job_failed",message:"The approved run committed, but Overview refresh failed."});return;}if(!latest.ok||latest.runId!==job.committedRunId||latest.dashboard.latestRun.runId!==job.committedRunId){dispatch({type:"job_failed",message:latest.ok?"The latest dashboard did not match the approved run.":latest.error.message});return;}sessionStorage.setItem("dengueops-latest-dashboard",JSON.stringify({runId:latest.runId,dashboard:latest.dashboard}));dispatch({type:"job_completed",runId:latest.runId,point:latest.dashboard.forecastCases,targetPeriod:latest.dashboard.targetPeriod,approved:true});window.location.assign("/dashboard");return;}if(["failed","timed_out","cancelled"].includes(job.status)){dispatch({type:"job_failed",status:job.status as "failed"|"timed_out"|"cancelled",message:job.error?.message??"The approved forecast failed; the previous Overview remains unchanged."});return;}await new Promise(resolve=>window.setTimeout(resolve,delay));delay=Math.min(10000,Math.round(delay*1.35));}
  };

  return <div className="space-y-6">
    <ForecastRunStepper current={state.step} />
    <div className="rounded-2xl border border-border-subtle bg-surface p-5 shadow-sm sm:p-7">
      {state.step === "upload" && <div className="grid gap-5 lg:grid-cols-2">
        <DatasetUploadPanel kind="dengue" preview={state.files.dengue} onChange={preview => dispatch({ type: "file", preview })} onRemove={() => dispatch({ type: "remove", key: "dengue" })} />
        <DatasetUploadPanel kind="climate" preview={state.files.climate} onChange={preview => dispatch({ type: "file", preview })} onRemove={() => dispatch({ type: "remove", key: "climate" })} />
      </div>}
      {state.step === "validate" && <DatasetValidationSummary
        files={state.files}
        mode={state.mode}
        serverValidation={state.serverValidation}
        onMode={mode => dispatch({ type: "mode", mode })}
        onValidate={() => void validate()}
      />}
      {state.step === "choose" && <WorkflowChoice value={state.mode} onChange={mode => dispatch({ type: "mode", mode })} />}
      {state.step === "review" && <div className="space-y-4">
        <div className="rounded-xl border border-border-subtle bg-surface-muted p-5">
          <h2 className="font-semibold text-ink">Review and execute</h2>
          <p className="mt-2 text-sm text-ink-muted">Files: {state.files.dengue?.file.name ?? "missing"} · {state.files.climate?.file.name ?? "missing"}</p>
          <p className="mt-1 text-sm text-ink-muted">Workflow: {state.mode === "quick_forecast" ? "Quick Forecast · deployment compatibility required · 2-week horizon" : "Assess Dataset · future candidate assessment · approval required"}</p>
          <p className="mt-2 text-xs text-ink-muted">Validated workspace: {state.workspaceId?.slice(0, 8)}… · Dataset: {state.datasetId?.slice(0, 8)}…</p>
        </div>
        <ProcessingState status={state.processingStatus} stage={state.job?.ok ? state.job.progress : undefined} workflow={state.mode} />
        {state.mode === "quick_forecast" ? <Button disabled={!selectedEligible || ["queued", "running", "committing"].includes(state.processingStatus)} onClick={() => void runQuickForecast()}>Start Quick Forecast</Button> : <Button disabled={!selectedEligible || ["queued", "running", "committing"].includes(state.processingStatus)} onClick={() => void runAssessment()}>Start Dataset Assessment</Button>}
      </div>}
      {state.step === "results" && (state.mode === "assess_dataset" ? <div className="space-y-5"><ModelSuitabilitySummary assessment={state.assessment} />{state.assessment?<ApprovalPanel assessment={state.assessment} decision={state.approval} busy={["queued","running","committing"].includes(state.processingStatus)} onDecision={(choice,reason)=>void recordDecision(choice,reason)} onForecast={()=>void runApprovedForecast()}/>:null}{state.approval?.forecastAuthorized?<ProcessingState status={state.processingStatus} stage={state.job?.ok?state.job.progress:undefined} workflow="assess_dataset"/>:null}</div> : <ForecastResultSummary result={state.result} />)}
    </div>
    <div className="flex justify-between gap-3">
      <Button variant="secondary" disabled={index === 0} onClick={() => dispatch({ type: "step", step: order[index - 1] })}>Back</Button>
      {state.step !== "review" && state.step !== "results"
        ? <Button disabled={!canNext} onClick={() => dispatch({ type: "step", step: order[index + 1] })}>Continue</Button>
        : null}
    </div>
  </div>;
}
