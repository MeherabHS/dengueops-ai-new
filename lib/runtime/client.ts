import type { CurrentModelAssignmentResponse, DatasetAssessmentResponse, DecisionChoice, DecisionResponse, JobStatusResponse, LatestDashboardResponse, ModelDegradationResponse, ModelLifecycleResponse, MonitoringSummaryResponse, RecordDecisionRequest, RuntimeValidationResponse, StartApprovedForecastRequest, StartApprovedForecastResponse, StartAssessmentRequest, StartAssessmentResponse, StartModelAssignmentRequest, StartModelAssignmentResponse, StartQuickForecastRequest, StartQuickForecastResponse, WorkflowMode } from "./contracts";

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

export async function recordAssessmentDecision(assessmentId:string,input:RecordDecisionRequest):Promise<DecisionResponse>;
export async function recordAssessmentDecision(assessmentId:string,input:{decision:DecisionChoice;reason:string;expectedAssessmentSummarySha256:string}):Promise<DecisionResponse>;
export async function recordAssessmentDecision(assessmentId:string,input:RecordDecisionRequest|{decision:DecisionChoice;reason:string;expectedAssessmentSummarySha256:string}):Promise<DecisionResponse>{const response=await fetch(`/api/runtime/assessments/${encodeURIComponent(assessmentId)}/decisions`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(input)});return await response.json() as DecisionResponse;}
export async function getDecision(decisionId:string):Promise<DecisionResponse>{const response=await fetch(`/api/runtime/decisions/${encodeURIComponent(decisionId)}`,{cache:"no-store"});return await response.json() as DecisionResponse;}
export async function startApprovedForecast(decisionId:string,input:StartApprovedForecastRequest):Promise<StartApprovedForecastResponse>{const response=await fetch(`/api/runtime/decisions/${encodeURIComponent(decisionId)}/forecast`,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(input)});return await response.json() as StartApprovedForecastResponse;}

export async function getCurrentModelAssignment(): Promise<CurrentModelAssignmentResponse> {
  const response = await fetch("/api/runtime/model-assignments", { cache: "no-store" });
  return await response.json() as CurrentModelAssignmentResponse;
}

export async function startModelAssignment(input: StartModelAssignmentRequest): Promise<StartModelAssignmentResponse> {
  const response = await fetch("/api/runtime/model-assignments", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return await response.json() as StartModelAssignmentResponse;
}

export async function getRuntimeJob(jobId: string): Promise<JobStatusResponse> {
  const response = await fetch(`/api/runtime/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
  return await response.json() as JobStatusResponse;
}

export async function getRuntimeJobByStatusUrl(statusUrl: string): Promise<JobStatusResponse> {
  if (!/^\/api\/runtime\/jobs\/[0-9a-f-]+$/i.test(statusUrl)) throw new Error("The returned job status URL is invalid.");
  const response = await fetch(statusUrl, { cache: "no-store" });
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
