import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const workflow = await read("components/forecast/OperationalForecastWorkflow.tsx");
const governance = await read("components/forecast/ForecastRunWorkflow.tsx");
const page = await read("app/forecast/run/page.tsx");
const stepper = await read("components/forecast/ForecastRunStepper.tsx");
const quickPanel = await read("components/forecast/QuickForecastRunPanel.tsx");

test("operational forecasting has a separate route, storage boundary, and five stages", () => {
  assert.match(page, /Run Operational Forecast/);
  assert.match(workflow, /dengueops-operational-forecast-workflow-v1/);
  assert.match(stepper, /Upload latest data/);
  assert.match(stepper, /Current verification/);
  assert.doesNotMatch(workflow, /dengueops-model-assessment-workflow-v1/);
  assert.doesNotMatch(governance, /QuickForecastRunPanel|workflowMode: "quick_forecast"/);
});

test("fresh validation is assignment-bound and browser model-free", () => {
  const request = workflow.slice(
    workflow.indexOf("validateRuntimeDatasets({"),
    workflow.indexOf("});", workflow.indexOf("validateRuntimeDatasets({")) + 3,
  );
  for (const field of ["dengueFile", "climateFile", "deploymentId", "workflowMode"]) {
    assert.match(request, new RegExp(field));
  }
  for (const forbidden of ["modelId", "candidateId", "selectedCandidateId", "assignmentId"]) {
    assert.doesNotMatch(request, new RegExp(forbidden));
  }
  assert.match(workflow, /authority\.assignmentId === assignment\.assignmentId/);
  assert.match(workflow, /authority\.authoritySnapshotSha256 === assignment\.assignmentPointerSha256/);
  assert.match(workflow, /authority\.modelId === assignment\.selectedCandidateId/);
});

test("refresh recovery retains only bounded started-job evidence", () => {
  assert.match(workflow, /if \(validation && next\.jobId\)/);
  assert.match(workflow, /boundedValidation/);
  assert.match(workflow, /boundedQuickForecast/);
  assert.match(workflow, /status: "recovering_existing_job"/);
  assert.match(workflow, /localStorage\.removeItem\(STORAGE_KEY\)/);
});

test("exact-current verification remains the dashboard handoff gate", () => {
  assert.match(quickPanel, /getLatestDashboard/);
  assert.match(quickPanel, /latest\.runId === committedRunId/);
  assert.match(quickPanel, /latest\.sourceType === "uploaded"/);
  assert.match(quickPanel, /status: "current_verified"/);
  assert.ok(quickPanel.indexOf('status: "current_verified"') < quickPanel.indexOf('router.push("/dashboard")'));
});
