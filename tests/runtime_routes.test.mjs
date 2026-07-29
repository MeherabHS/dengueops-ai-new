import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const route = await read("app/api/runtime/validate/route.ts");
const uploads = await read("lib/runtime/uploads.ts");
const workflow = await read("components/forecast/ForecastRunWorkflow.tsx");
const assessmentOption = await read("components/forecast/DatasetAssessmentOption.tsx");
const forecastPage = await read("app/forecast/page.tsx");

test("validation route remains Node-only, multipart, bounded, and shell-free", () => {
  assert.match(route, /export const runtime = "nodejs"/);
  assert.match(route, /request\.formData\(\)/);
  assert.match(route, /getAll\(name\)/);
  assert.match(route, /shell: false/);
  assert.match(route, /validationTimeoutMs/);
});

test("CSV upload inspection rejects unsafe input classes", () => {
  for (const marker of ["invalid_file_extension", "upload_too_large", "nul_byte_detected", "invalid_utf8", "duplicate_csv_header", "inconsistent_csv_width"]) assert.match(uploads, new RegExp(marker));
  assert.match(uploads, /safeOriginalName/);
});

test("B9.4B validates only the assessment workspace and does not start Quick Forecast", () => {
  assert.match(workflow, /workflowMode: "assess_dataset"/);
  assert.match(workflow, /startDatasetAssessment/);
  assert.doesNotMatch(workflow, /startQuickForecast|location\.assign|getLatestDashboard/);
  assert.match(assessmentOption, /current governed temporal assessment/);
  assert.match(forecastPage, /explicit governed expert override/);
});

test("validation and assessment never publish a decision or approved forecast automatically", () => {
  const validationBranch = workflow.slice(workflow.indexOf("const validate"), workflow.indexOf("const runAssessment"));
  const assessmentBranch = workflow.slice(workflow.indexOf("const runAssessment"), workflow.indexOf("const recordDecision"));
  for (const branch of [validationBranch, assessmentBranch]) assert.doesNotMatch(branch, /recordAssessmentDecision|startApprovedForecast/);
});
