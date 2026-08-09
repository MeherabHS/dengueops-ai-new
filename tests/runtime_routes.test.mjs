import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const route = await read("app/api/runtime/validate/route.ts");
const uploads = await read("lib/runtime/uploads.ts");
const workflow = await read("components/forecast/ForecastRunWorkflow.tsx");
const operationalWorkflow = await read("components/forecast/OperationalForecastWorkflow.tsx");
const quickPanel = await read("components/forecast/QuickForecastRunPanel.tsx");
const quickRoute = await read("app/api/runtime/runs/quick/route.ts");
const contracts = await read("lib/runtime/contracts.ts");
const assessmentOption = await read("components/forecast/DatasetAssessmentOption.tsx");
const forecastPage = await read("app/forecast/page.tsx");

test("validation route remains Node-only, multipart, bounded, and shell-free", () => {
  assert.match(route, /export const runtime = "nodejs"/);
  assert.match(route, /readBoundedFormData\(request,/);
  assert.match(route, /getAll\(name\)/);
  assert.match(route, /shell: false/);
  assert.match(route, /validationTimeoutMs/);
  assert.ok(route.indexOf("await requireSuperUserMutation(request)") < route.indexOf("await readBoundedFormData(request"));
  assert.match(route, /new Set\(\["dengueFile", "climateFile", "deploymentId", "workflowMode"\]\)/);
});

test("CSV upload inspection rejects unsafe input classes", () => {
  for (const marker of ["invalid_file_extension", "upload_too_large", "nul_byte_detected", "invalid_utf8", "duplicate_csv_header", "inconsistent_csv_width"]) assert.match(uploads, new RegExp(marker));
  assert.match(uploads, /safeOriginalName/);
});

test("governance and operational forecasting use separate deliberate handoffs", () => {
  assert.match(workflow, /workflowMode: "assess_dataset"/);
  assert.match(workflow, /startDatasetAssessment/);
  assert.doesNotMatch(workflow, /workflowMode: "quick_forecast"|<QuickForecastRunPanel/);
  assert.match(operationalWorkflow, /workflowMode: "quick_forecast"/);
  assert.match(operationalWorkflow, /<QuickForecastRunPanel/);
  assert.match(quickPanel, /startQuickForecast\(request\)/);
  assert.doesNotMatch(workflow, /location\.assign|getLatestDashboard/);
  assert.match(assessmentOption, /current governed temporal assessment/);
  assert.match(forecastPage, /explicit governed expert override/);
});

test("Quick Forecast mutation authenticates before parsing and rejects unbounded fields", () => {
  assert.ok(quickRoute.indexOf("await requireSuperUserMutation(request)") < quickRoute.indexOf("await readBoundedJson"));
  assert.match(quickRoute, /expectedAssignmentPointerSha256/);
  assert.match(quickRoute, /unexpected_quick_forecast_field/);
  assert.match(quickRoute, /quick_forecast_assignment_conflict/);
  assert.doesNotMatch(quickPanel, /modelId:|candidateId:|selectedCandidateId:/);
});

test("Quick Forecast start and recovery expose one sanitized response contract", () => {
  const response = quickRoute.slice(quickRoute.indexOf("function successResponse"), quickRoute.indexOf("function canonicalPolicySha256"));
  for (const marker of ["jobId", "runId", "status", "statusUrl", "deploymentId", "recovered", "activeModelAuthority"]) assert.match(response, new RegExp(marker));
  assert.doesNotMatch(response, /path|command|markerContents|policyContents|environment/i);
  assert.match(quickRoute, /status: 202/);
  assert.match(quickRoute, /status: 200/);
  assert.match(quickRoute, /quick_forecast_publication_in_progress/);
});

test("validation success returns only a server-verified bounded workflow mode", () => {
  assert.match(contracts, /workflowMode: "quick_forecast" \| "assess_dataset"/);
  assert.match(route, /const verifiedWorkflowMode = validation\.workflowMode/);
  assert.match(route, /verifiedWorkflowMode !== "quick_forecast" && verifiedWorkflowMode !== "assess_dataset"/);
  assert.match(route, /verifiedWorkflowMode !== input\.requestedWorkflowMode/);
  assert.match(route, /workflowMode: verifiedWorkflowMode/);
  assert.doesNotMatch(route, /workflowMode:\s*workflowMode,/);
});

test("validation artifact workflow mode fails closed when missing, unsupported, or mismatched", () => {
  assert.match(route, /workflowMode\?: unknown/);
  assert.equal((route.match(/invalid_validation_output/g) ?? []).length >= 3, true);
  assert.match(route, /Authoritative validation returned an invalid workflow mode/);
  assert.match(route, /Authoritative validation did not match the requested workflow mode/);
  assert.match(route, /workflowModeValue !== "quick_forecast" && workflowModeValue !== "assess_dataset"/);
});

test("Quick Forecast validation reconciles persisted assignment binding with current authority", () => {
  assert.match(route, /validationAuthorityMatches/);
  assert.match(route, /validation\.activeModelAuthority/);
  assert.match(route, /validation\.eligibility\.quickForecast\.assignedCandidateId !== currentAuthority\.modelId/);
  assert.match(route, /quick_validation_authority_mismatch/);
  assert.doesNotMatch(route, /approvedModelId === currentAuthority\.modelId/);
});

test("validation contracts keep assessment 1.0 separate from assignment-bound Quick 1.1", () => {
  assert.match(contracts, /approvedModelId: CurrentSelectableCandidateId/);
  assert.match(contracts, /assignedCandidateId: CurrentSelectableCandidateId/);
  assert.match(contracts, /assignedCandidateId\?: never/);
  assert.match(contracts, /approvedModelId\?: never/);
  assert.match(route, /validationAuthorityMatches/);
});

test("validation and assessment never publish a decision or approved forecast automatically", () => {
  const validationBranch = workflow.slice(workflow.indexOf("const validate ="), workflow.indexOf("const runAssessment"));
  const assessmentBranch = workflow.slice(workflow.indexOf("const runAssessment"), workflow.indexOf("const recordDecision"));
  for (const branch of [validationBranch, assessmentBranch]) assert.doesNotMatch(branch, /recordAssessmentDecision|startApprovedForecast/);
  assert.doesNotMatch(validationBranch, /startQuickForecast|\/api\/runtime\/runs\/quick/);
});
