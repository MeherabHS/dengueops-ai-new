import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const route = await read("app/api/runtime/validate/route.ts");
const uploads = await read("lib/runtime/uploads.ts");
const workflow = await read("components/forecast/ForecastRunWorkflow.tsx");
const contracts = await read("lib/runtime/contracts.ts");
const assessmentOption = await read("components/forecast/DatasetAssessmentOption.tsx");
const forecastPage = await read("app/forecast/page.tsx");

test("validation route remains Node-only, multipart, bounded, and shell-free", () => {
  assert.match(route, /export const runtime = "nodejs"/);
  assert.match(route, /request\.formData\(\)/);
  assert.match(route, /getAll\(name\)/);
  assert.match(route, /shell: false/);
  assert.match(route, /validationTimeoutMs/);
  assert.ok(route.indexOf("await requireSuperUserMutation(request)") < route.indexOf("await request.formData()"));
  assert.match(route, /new Set\(\["dengueFile", "climateFile", "deploymentId", "workflowMode"\]\)/);
});

test("CSV upload inspection rejects unsafe input classes", () => {
  for (const marker of ["invalid_file_extension", "upload_too_large", "nul_byte_detected", "invalid_utf8", "duplicate_csv_header", "inconsistent_csv_width"]) assert.match(uploads, new RegExp(marker));
  assert.match(uploads, /safeOriginalName/);
});

test("B9.4C2 supports fresh Quick Forecast validation without starting Quick Forecast", () => {
  assert.match(workflow, /workflowMode: "assess_dataset"/);
  assert.match(workflow, /workflowMode: "quick_forecast"/);
  assert.match(workflow, /startDatasetAssessment/);
  assert.doesNotMatch(workflow, /startQuickForecast|location\.assign|getLatestDashboard/);
  assert.match(assessmentOption, /current governed temporal assessment/);
  assert.match(forecastPage, /explicit governed expert override/);
});

test("validation success returns only a server-verified bounded workflow mode", () => {
  assert.match(contracts, /workflowMode: "quick_forecast" \| "assess_dataset"/);
  assert.match(route, /const verifiedWorkflowMode = validation\.workflowMode/);
  assert.match(route, /verifiedWorkflowMode !== "quick_forecast" && verifiedWorkflowMode !== "assess_dataset"/);
  assert.match(route, /verifiedWorkflowMode !== workflowMode/);
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

test("validation and assessment never publish a decision or approved forecast automatically", () => {
  const validationBranch = workflow.slice(workflow.indexOf("const validate ="), workflow.indexOf("const runAssessment"));
  const assessmentBranch = workflow.slice(workflow.indexOf("const runAssessment"), workflow.indexOf("const recordDecision"));
  for (const branch of [validationBranch, assessmentBranch]) assert.doesNotMatch(branch, /recordAssessmentDecision|startApprovedForecast/);
  assert.doesNotMatch(validationBranch, /startQuickForecast|\/api\/runtime\/runs\/quick/);
});
