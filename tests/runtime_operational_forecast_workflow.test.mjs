import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const workflow = await read("components/forecast/OperationalForecastWorkflow.tsx");
const governance = await read("components/forecast/ForecastRunWorkflow.tsx");
const page = await read("app/forecast/run/page.tsx");
const stepper = await read("components/forecast/ForecastRunStepper.tsx");
const quickPanel = await read("components/forecast/QuickForecastRunPanel.tsx");
const client = await read("lib/runtime/client.ts");
const validationRoute = await read("app/api/runtime/validate/route.ts");
const assessmentSource = await read("lib/runtime/assessment-dataset-source.ts");

function loadBoundedRecoveryProjectors() {
  const start = workflow.indexOf("const UUID");
  const end = workflow.indexOf("export default function OperationalForecastWorkflow");
  assert.ok(start >= 0 && end > start);
  const source = `${workflow.slice(start, end)}\n;globalThis.__operationalRecoveryProjectors = { boundedValidation, boundedQuickForecast };`;
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2022 } }).outputText;
  return new Function(`${compiled}\nreturn globalThis.__operationalRecoveryProjectors;`)();
}

test("operational forecasting has a separate route, storage boundary, and five stages", () => {
  assert.match(page, /Run Operational Forecast/);
  assert.match(workflow, /dengueops-operational-forecast-workflow-v1/);
  assert.match(stepper, /Upload latest data/);
  assert.match(stepper, /Current verification/);
  assert.doesNotMatch(workflow, /dengueops-model-assessment-workflow-v1/);
  assert.doesNotMatch(governance, /QuickForecastRunPanel|workflowMode: "quick_forecast"/);
});

test("assignment complete offers a bounded assessed-data handoff and the newer-upload path", () => {
  assert.match(governance, /Run forecast with assessed dataset/);
  assert.match(governance, /href="\/forecast\/run\?source=assessed"/);
  assert.match(governance, /Forecast with newer data/);
  assert.doesNotMatch(governance, />Use newer datasets<\/Link>/);
  assert.match(governance, /href="\/forecast\/run\?source=new"/);
  assert.match(governance, /Reassess models with updated data/);
  assert.match(governance, /href="\/forecast\?intent=reassess"/);
  assert.match(page, /query\.source === "assessed"/);
  assert.match(page, /query\.source === "new"/);
  assert.match(page, /"new_assessed"/);
  assert.match(page, /"new_upload"/);
  assert.match(page, /: "resume"/);
  assert.match(page, /initialSource=\{initialSource\}/);
  assert.match(page, /entryIntent=\{entryIntent\}/);
  assert.match(workflow, /Using the validated dataset from the completed model assessment/);
  assert.match(workflow, /Continue to operational validation/);
  assert.match(workflow, /Use newer datasets instead/);
  assert.match(workflow, /sourceMode === "newer"[\s\S]*DatasetUploadPanel/);
});

test("assessed dataset request is bounded and browser model/path free", () => {
  const handoff = client.slice(client.indexOf("export async function validateAssessedDataset"), client.indexOf("export async function startQuickForecast"));
  assert.match(handoff, /source: "current_assignment_assessment"/);
  assert.doesNotMatch(handoff, /assessmentId|workspaceId|modelId|candidateId|assignmentId|file|path/i);
  assert.match(validationRoute, /await requireSuperUserMutation\(request\)/);
  assert.match(validationRoute, /Object\.keys\(body\)\.sort\(\)\.join\("\|"\) !== "source"/);
  assert.match(validationRoute, /resolveCurrentAssessmentDataset\(config\)/);
});

test("server resolves immutable assessment inputs into a distinct idempotent operational workspace", () => {
  for (const evidence of [
    "sourceAssessmentId",
    "assessmentCommitSha256",
    "input_manifest.json",
    "validationRecordSha256",
    "dengueCanonical",
    "climateCanonical",
    "candidateRegistrySha256",
    "featureOrderSha256",
  ]) assert.match(assessmentSource, new RegExp(evidence.replace(".", "\\.")));
  assert.match(assessmentSource, /operationalWorkspaceId: deterministicWorkspaceId\(sourceSnapshotSha256\)/);
  assert.match(validationRoute, /source\?\.operationalWorkspaceId \?\? randomUUID\(\)/);
  assert.match(validationRoute, /recoverAssessmentHandoff/);
  assert.match(validationRoute, /assessment_dataset_handoff_in_progress/);
  assert.match(validationRoute, /assessment_dataset_materialized/);
  assert.match(validationRoute, /requestedWorkflowMode: "quick_forecast"/);
  assert.doesNotMatch(assessmentSource, /writeFile|rename|rm\(/);
});

test("assessed data still passes fresh current-assignment validation before forecast", () => {
  const assessedValidation = workflow.slice(workflow.indexOf("const validateAssessmentSource"), workflow.indexOf("const updateQuickForecast"));
  assert.match(assessedValidation, /validateAssessedDataset\(\)/);
  assert.match(assessedValidation, /acceptValidation\(response, assignment\)/);
  assert.doesNotMatch(assessedValidation, /startQuickForecast|recordAssessmentDecision|startModelAssignment/);
  assert.match(validationRoute, /runPythonValidation/);
  assert.match(validationRoute, /validationAuthorityMatches/);
  assert.match(validationRoute, /assignedCandidateId !== currentAuthority\.modelId/);
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
  assert.match(workflow, /authority\.assignmentId === currentAssignment\.assignmentId/);
  assert.match(workflow, /authority\.authoritySnapshotSha256 === currentAssignment\.assignmentPointerSha256/);
  assert.match(workflow, /authority\.modelId === currentAssignment\.selectedCandidateId/);
});

test("refresh recovery retains only bounded started-job evidence", () => {
  assert.match(workflow, /if \(validation && next\.jobId\)/);
  assert.match(workflow, /boundedValidation/);
  assert.match(workflow, /boundedQuickForecast/);
  assert.match(workflow, /status: "recovering_existing_job"/);
  assert.match(workflow, /localStorage\.removeItem\(STORAGE_KEY\)/);
});

test("explicit new-forecast intents clear only browser workflow recovery state", () => {
  const recoveryEffect = workflow.slice(workflow.indexOf("const recover = async"), workflow.indexOf("const resetValidation"));
  assert.match(recoveryEffect, /entryIntent !== "resume"/);
  assert.match(recoveryEffect, /localStorage\.removeItem\(STORAGE_KEY\)/);
  assert.match(recoveryEffect, /window\.history\.replaceState\(window\.history\.state, "", "\/forecast\/run"\)/);
  assert.ok(recoveryEffect.indexOf('entryIntent !== "resume"') < recoveryEffect.indexOf("localStorage.getItem(STORAGE_KEY)"));
  assert.doesNotMatch(recoveryEffect, /router\.|\/dashboard|validateAssessedDataset|validateRuntimeDatasets|startQuickForecast|signOut|sessionStorage/);
});

test("completed current forecast state cannot become a new active workflow", () => {
  const { boundedQuickForecast } = loadBoundedRecoveryProjectors();
  const completed = {
    jobId: "33333333-3333-4333-8333-333333333333",
    expectedRunId: "44444444-4444-4444-8444-444444444444",
    committedRunId: "44444444-4444-4444-8444-444444444444",
    exactCurrentRunId: "44444444-4444-4444-8444-444444444444",
    statusUrl: "/api/runtime/jobs/33333333-3333-4333-8333-333333333333",
    status: "current_verified",
  };
  assert.equal(boundedQuickForecast(completed), null);
  assert.doesNotMatch(workflow, /router\.(?:push|replace)|location\.(?:assign|replace)|redirect\("\/dashboard"\)/);
});

test("retained operational recovery revalidates assignment and resumes GET-only polling behavior", async () => {
  const { boundedValidation, boundedQuickForecast } = loadBoundedRecoveryProjectors();
  const assignment = {
    assignmentId: "11111111-1111-4111-8111-111111111111",
    assignmentPointerSha256: "a".repeat(64),
    selectedCandidateId: "hist_gradient_boosting",
  };
  const retained = {
    validation: {
      workspaceId: "22222222-2222-4222-8222-222222222222",
      datasetId: "dataset-identity",
      deploymentId: "dhaka_south",
      validationRecordSha256: "b".repeat(64),
      workflowMode: "quick_forecast",
      assignmentId: assignment.assignmentId,
      assignmentPointerSha256: assignment.assignmentPointerSha256,
      selectedCandidateId: assignment.selectedCandidateId,
    },
    quickForecast: {
      jobId: "33333333-3333-4333-8333-333333333333",
      expectedRunId: "44444444-4444-4444-8444-444444444444",
      statusUrl: "/api/runtime/jobs/33333333-3333-4333-8333-333333333333",
      status: "running",
    },
  };
  const calls = [];
  const current = await (async () => { calls.push("GET current assignment"); return assignment; })();
  const validation = boundedValidation(retained.validation);
  const forecast = boundedQuickForecast(retained.quickForecast);
  assert.ok(validation && forecast);
  assert.equal(validation.assignmentId, current.assignmentId);
  assert.equal(validation.assignmentPointerSha256, current.assignmentPointerSha256);
  assert.equal(validation.selectedCandidateId, current.selectedCandidateId);
  assert.equal(forecast.status, "recovering_existing_job");
  await (async () => { calls.push(`GET ${forecast.statusUrl}`); })();
  assert.deepEqual(calls, ["GET current assignment", `GET ${forecast.statusUrl}`]);
  assert.equal(calls.some((call) => call.startsWith("POST")), false);

  const recoveryEffect = workflow.slice(workflow.indexOf("const recover = async"), workflow.indexOf("const resetValidation"));
  const resumeEffect = quickPanel.slice(quickPanel.indexOf("useEffect(() => {\n    if (!entryVerified"), quickPanel.indexOf("useEffect(() => {\n    if (\n      state.status"));
  assert.match(recoveryEffect, /const current = await readAssignment\(\)/);
  assert.match(resumeEffect, /void pollJob\(state\.jobId, state\.expectedRunId, state\.statusUrl\)/);
  assert.doesNotMatch(`${recoveryEffect}\n${resumeEffect}`, /startQuickForecast\(|recoverQuickForecastStart\(/);
});

test("exact-current verification remains the dashboard handoff gate", () => {
  assert.match(quickPanel, /getLatestDashboard/);
  assert.match(quickPanel, /latest\.runId === committedRunId/);
  assert.match(quickPanel, /latest\.sourceType === "uploaded"/);
  assert.match(quickPanel, /status: "current_verified"/);
  assert.match(quickPanel, /state\.committedRunId !== state\.expectedRunId/);
  assert.ok(quickPanel.indexOf('status: "current_verified"') < quickPanel.indexOf('router.push("/dashboard")'));
});
