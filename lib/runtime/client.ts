import type { DatasetAssessmentResponse, DecisionResponse, JobStatusResponse, LatestDashboardResponse, ModelDegradationResponse, ModelLifecycleResponse, MonitoringSummaryResponse, RecordDecisionRequest, RuntimeValidationResponse, StartApprovedForecastRequest, StartApprovedForecastResponse, StartAssessmentRequest, StartAssessmentResponse, StartQuickForecastRequest, StartQuickForecastResponse, WorkflowMode } from "./contracts";

export async function validateRuntimeDatasets(input: {
  dengueFile: File;
  climateFile: File;
  deploymentId: string;
  workflowMode: WorkflowMode;
  signal?: AbortSignal;
}): Promise<RuntimeValidationResponse> {
  const form = new FormData();
  form.append("dengueFile", input.dengueFile);
  form.append("climateFile", input.climateFile);
  form.append("deploymentId", input.deploymentId);
  form.append("workflowMode", input.workflowMode);
  const response = await fetch("/api/runtime/validate", { method: "POST", body: form, signal: input.signal });
  const payload = (await response.json()) as RuntimeValidationResponse;
  return payload;
}

export async function startQuickForecast(input: StartQuickForecastRequest): Promise<StartQuickForecastResponse> {
  const response = await fetch("/api/runtime/runs/quick", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) });
  return await response.json() as StartQuickForecastResponse;
}

export async function startDatasetAssessment(input: StartAssessmentRequest): Promise<StartAssessmentResponse> {
  const response = await fetch("/api/runtime/assessments", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(input) });
  return await response.json() as StartAssessmentResponse;
}

export async function getDatasetAssessment(assessmentId: string): Promise<DatasetAssessmentResponse> {
  const response = await fetch(`/api/runtime/assessments/${encodeURIComponent(assessmentId)}`, { cache: "no-store" });
  return await response.json() as DatasetAssessmentResponse;
}

export async function recordAssessmentDecision(assessmentId:string,input:RecordDecisionRequest):Promise<DecisionResponse>{const response=await fetch(`/api/runtime/assessments/${encodeURIComponent(assessmentId)}/decisions`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(input)});return await response.json() as DecisionResponse;}
export async function getDecision(decisionId:string):Promise<DecisionResponse>{const response=await fetch(`/api/runtime/decisions/${encodeURIComponent(decisionId)}`,{cache:"no-store"});return await response.json() as DecisionResponse;}
export async function startApprovedForecast(decisionId:string,input:StartApprovedForecastRequest):Promise<StartApprovedForecastResponse>{const response=await fetch(`/api/runtime/decisions/${encodeURIComponent(decisionId)}/forecast`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(input)});return await response.json() as StartApprovedForecastResponse;}

export async function getRuntimeJob(jobId: string): Promise<JobStatusResponse> {
  const response = await fetch(`/api/runtime/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
  return await response.json() as JobStatusResponse;
}

export async function getLatestDashboard(deploymentId = "dhaka_south"): Promise<LatestDashboardResponse> {
  const response = await fetch(`/api/dashboard/latest?deployment=${encodeURIComponent(deploymentId)}`, { cache: "no-store" });
  return await response.json() as LatestDashboardResponse;
}

export async function getMonitoringSummary(deploymentId="dhaka_south"):Promise<MonitoringSummaryResponse>{
  const response=await fetch(`/api/runtime/monitoring/summary?deploymentId=${encodeURIComponent(deploymentId)}`,{cache:"no-store"});
  return await response.json() as MonitoringSummaryResponse;
}
export async function getModelDegradationEvidence(deploymentId="dhaka_south"):Promise<ModelDegradationResponse>{const response=await fetch(`/api/runtime/model-degradation-evidence?deploymentId=${encodeURIComponent(deploymentId)}`,{cache:"no-store"});return await response.json() as ModelDegradationResponse;}
export async function getModelLifecycle():Promise<ModelLifecycleResponse>{const response=await fetch("/api/runtime/model-lifecycle",{cache:"no-store"});return await response.json() as ModelLifecycleResponse;}
