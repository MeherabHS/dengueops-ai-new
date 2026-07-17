import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const route = await readFile(new URL("../app/api/runtime/validate/route.ts", import.meta.url), "utf8");
const uploads = await readFile(new URL("../lib/runtime/uploads.ts", import.meta.url), "utf8");
const workflow = await readFile(new URL("../components/forecast/ForecastRunWorkflow.tsx", import.meta.url), "utf8");
const workflowChoice = await readFile(new URL("../components/forecast/WorkflowChoice.tsx", import.meta.url), "utf8");
const assessmentOption = await readFile(new URL("../components/forecast/DatasetAssessmentOption.tsx", import.meta.url), "utf8");
const forecastPage = await readFile(new URL("../app/forecast/page.tsx", import.meta.url), "utf8");
const workflowTypes = await readFile(new URL("../lib/forecast-workflow-types.ts", import.meta.url), "utf8");
const statusLabels = await readFile(new URL("../lib/status-labels.ts", import.meta.url), "utf8");

test("validation route is Node-only, multipart, bounded, and shell-free", () => {
  assert.match(route, /export const runtime = "nodejs"/);
  assert.match(route, /request\.formData\(\)/);
  assert.match(route, /getAll\(name\)/);
  assert.match(route, /shell: false/);
  assert.match(route, /validationTimeoutMs/);
});

test("CSV upload inspection rejects unsafe input classes", () => {
  for (const marker of ["invalid_file_extension", "upload_too_large", "nul_byte_detected", "invalid_utf8", "duplicate_csv_header", "inconsistent_csv_width"]) {
    assert.match(uploads, new RegExp(marker));
  }
  assert.match(uploads, /path\.basename\(name\)/);
  assert.match(uploads, /safeOriginalName/);
});

test("frontend starts only eligible Quick Forecast and refreshes only after commit", () => {
  assert.match(workflow, /validateRuntimeDatasets/);
  assert.match(workflow, /Start Quick Forecast/);
  assert.match(workflow, /job\.status === "completed"/);
  assert.match(workflow, /latest\.runId !== job\.committedRunId/);
  assert.doesNotMatch(workflow, /setInterval|run_pipeline|EventSource|WebSocket/);
});

test("authoritative validation reaches workflow choice without preselected eligibility", () => {
  assert.match(workflow, /state\.step === "validate"[\s\S]*?Boolean\(response\?\.status === "ready"\)/);
  assert.match(workflow, /validatedWorkflowMode: action\.response\.status === "ready" \? state\.mode : null/);
  assert.match(workflowTypes, /validatedWorkflowMode: WorkflowMode \| null/);
});

test("Continue and execution require the selected workflow-specific workspace", () => {
  const readiness = workflow.slice(workflow.indexOf("const selectedWorkspaceReady"), workflow.indexOf("const canNext"));
  for (const marker of ["selectedEligible", "state.mode === state.validatedWorkflowMode", "state.workspaceId", "state.datasetId", "response.validationRecordSha256"]) {
    assert.match(readiness, new RegExp(marker.replaceAll(".", "\\.")));
  }
  assert.match(workflow, /state\.validatedWorkflowMode !== "quick_forecast"/);
  assert.match(workflow, /state\.validatedWorkflowMode !== "assess_dataset"/);
  assert.match(workflow, /disabled=\{!selectedWorkspaceReady/);
});

test("changing workflow atomically returns to Validate and clears only workflow-specific state", () => {
  const modeCase = workflow.slice(workflow.indexOf('case "mode"'), workflow.indexOf('case "step"'));
  assert.match(modeCase, /state\.validatedWorkflowMode !== action\.mode/);
  assert.match(modeCase, /resetValidation\(\{ \.\.\.state, mode: action\.mode \}\)/);
  assert.match(modeCase, /step: "validate"/);
  assert.match(modeCase, /workflowRevalidationRequired: true/);
  assert.doesNotMatch(modeCase, /files:\s*\{\}/);
  const reset = workflow.slice(workflow.indexOf("function resetValidation"), workflow.indexOf("function reducer"));
  assert.match(reset, /workspaceId: null/);
  assert.match(reset, /datasetId: null/);
  assert.match(reset, /serverValidation: \{ status: "idle" \}/);
});

test("workflow choice displays both authoritative eligibility and API reasons", () => {
  assert.match(workflowChoice, /response\.eligibility\.quickForecast/);
  assert.match(workflowChoice, /response\.eligibility\.assessDataset/);
  assert.match(workflowChoice, /eligibility\.reasons\.map/);
  assert.match(workflowChoice, /Revalidation required/);
  assert.match(workflow, /revalidationRequired=\{state\.workflowRevalidationRequired\}/);
});

test("obsolete runtime-preview copy is removed", () => {
  const combined = [forecastPage, workflowChoice, assessmentOption, statusLabels].join("\n");
  assert.doesNotMatch(combined, /Runtime connector pending P1\.4/i);
  assert.doesNotMatch(combined, /future governed runtime connector/i);
  assert.doesNotMatch(combined, /not yet connected/i);
  assert.doesNotMatch(statusLabels, /pending_p1_4/);
  assert.match(assessmentOption, /52-68 fold temporal assessment/);
  assert.match(assessmentOption, /most recent 68/);
  assert.match(assessmentOption, /older rows remain in expanding training/);
  assert.match(assessmentOption, /does not automatically deploy or adopt a model/);
});

test("validation and assessment do not refresh Overview", () => {
  const validationBranch = workflow.slice(workflow.indexOf("const validate"), workflow.indexOf("const runQuickForecast"));
  const assessmentBranch = workflow.slice(workflow.indexOf("const runAssessment"), workflow.indexOf("const recordDecision"));
  for (const branch of [validationBranch, assessmentBranch]) assert.doesNotMatch(branch, /getLatestDashboard|location\.assign|sessionStorage/);
});
