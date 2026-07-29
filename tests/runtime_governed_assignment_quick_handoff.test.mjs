import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [panel, workflow, client, contracts, route] = await Promise.all([
  read("components/forecast/ModelAssignmentPanel.tsx"),
  read("components/forecast/ForecastRunWorkflow.tsx"),
  read("lib/runtime/client.ts"),
  read("lib/runtime/contracts.ts"),
  read("app/api/runtime/model-assignments/route.ts"),
]);

test("approved forecast terminal evidence is reverified before assignment authority is read", () => {
  const verify = panel.slice(panel.indexOf("const verifiedApprovedRun"), panel.indexOf("const nextForDifferentCurrent"));
  assert.match(verify, /getRuntimeJob\(approvedForecast\.jobId\)/);
  for (const marker of [
    'job.jobKind !== "approved_forecast"',
    'job.status !== "completed"',
    "job.committedRunId !== approvedForecast.committedRunId",
    "job.decisionId !== approvedForecast.sourceDecisionId",
    "job.approvedForecastCommitSha256 !== approvedForecast.approvedForecastCommitSha256",
  ]) assert.match(verify, new RegExp(marker.replaceAll(".", "\\.")));
  const currentRead = panel.indexOf("getCurrentModelAssignment()");
  assert.ok(currentRead > panel.indexOf("await verifiedApprovedRun()"));
});

test("current optimistic-concurrency identity comes only from authenticated GET evidence", () => {
  assert.match(client, /fetch\("\/api\/runtime\/model-assignments", \{ cache: "no-store" \}\)/);
  assert.match(panel, /expectedAssignmentPointerSha256: current\.assignmentPointerSha256/);
  assert.match(route, /assignmentPointerSha256: active\.authoritySnapshotSha256/);
  assert.doesNotMatch(panel, /createHash|sha256|crypto|JSON\.stringify\(.*pointer/);
  assert.match(contracts, /selectedCandidateId: CurrentRuntimeCandidateId/);
});

test("assignment request is exact and contains no browser-selected model identity", () => {
  const publish = panel.slice(panel.indexOf("const publish"), panel.indexOf("const refresh"));
  const call = publish.slice(publish.indexOf("startModelAssignment"), publish.indexOf("if (response.ok)"));
  for (const marker of [
    "approvedForecastRunId:",
    "expectedApprovedForecastCommitSha256:",
    "expectedAssignmentPointerSha256:",
    "reason: trimmedReason",
    "assignmentAcknowledged: true",
  ]) assert.match(call, new RegExp(marker));
  assert.doesNotMatch(call, /modelId|candidateId|selectedCandidateId|assessmentId|decisionId|assignmentId|pointerContents/);
  assert.match(route, /REQUEST_KEYS/);
  assert.doesNotMatch(route, /body\.(?:modelId|candidateId|selectedCandidateId)/);
});

test("reason, acknowledgement, and synchronous duplicate protection gate publication", () => {
  assert.match(panel, /MIN_REASON_LENGTH = 12/);
  assert.match(panel, /MAX_REASON_LENGTH = 1000/);
  assert.match(panel, /reason\.trim\(\)\.length/);
  assert.match(panel, /assignmentAcknowledged: true/);
  assert.match(panel, /publishing\.current/);
  assert.match(panel, /publishing\.current = true/);
  assert.match(panel, /state\.status !== "ready"/);
  assert.equal((panel.match(/startModelAssignment\(/g) ?? []).length, 1);
  assert.doesNotMatch(panel, /<select|type="text".*(?:model|candidate)|placeholder=.*(?:model|candidate)/i);
});

test("POST success is reconciled through GET before assignment completion", () => {
  assert.match(panel, /if \(response\.ok\) \{\s*await verifyCurrent\("failed_uncertain", response, expectedPointer\)/);
  for (const marker of [
    "current.assignmentId === posted.assignmentId",
    "current.sourceApprovedForecastRunId === approvedForecast.committedRunId",
    "current.selectedCandidateId === posted.selectedCandidateId",
    'current.status === "assigned"',
    "current.assignmentPointerSha256 !== priorPointerSha256",
  ]) assert.match(panel, new RegExp(marker.replaceAll(".", "\\.")));
  assert.match(panel, /status: "assigned_verified"/);
  assert.match(workflow, /state\.assignment\.status === "assigned_verified"\) return "assignment"/);
});

test("lost responses recover only when the current source run and candidate match", () => {
  assert.match(panel, /catch \{\s*await verifyCurrent\("failed_uncertain"\)/);
  assert.match(panel, /const sourceMatches = current\.sourceApprovedForecastRunId === approvedForecast\.committedRunId/);
  assert.match(panel, /const candidateMatches = current\.selectedCandidateId === approvedForecast\.selectedModelId/);
  assert.match(panel, /if \(sourceMatches && candidateMatches\)[\s\S]*status: "assigned_verified"/);
  assert.match(panel, /nextForDifferentCurrent\(mode, current\)/);
});

test("pointer conflicts and publication locks never retry assignment automatically", () => {
  assert.match(panel, /response\.error\.code === "assignment_pointer_conflict"/);
  assert.match(panel, /response\.error\.code === "assignment_publication_in_progress"/);
  assert.match(panel, /No assignment retry will occur automatically/);
  assert.match(panel, /Refresh current assignment/);
  assert.equal((panel.match(/startModelAssignment\(/g) ?? []).length, 1);
  assert.ok(panel.indexOf("getCurrentModelAssignment()") < panel.indexOf("const publish ="));
});

test("refresh recovery retains local evidence but rechecks both server authorities", () => {
  assert.match(workflow, /assignment\?: Partial<ModelAssignmentWorkflowState>/);
  assert.match(workflow, /boundedRetainedAssignment/);
  assert.match(workflow, /status: "loading_current_assignment"/);
  assert.match(panel, /loadedEvidenceKey/);
  assert.match(panel, /await verifiedApprovedRun\(\)[\s\S]*getCurrentModelAssignment\(\)/);
  const recovery = workflow.slice(workflow.indexOf("useEffect(() => {\n    if (recoveryStarted"), workflow.indexOf("const setFile"));
  assert.doesNotMatch(recovery, /startModelAssignment|startQuickForecast|validateRuntimeDatasets/);
});

test("C1 stops with verified assignment and leaves Quick Forecast and dashboard pending", () => {
  assert.match(panel, /Governed assignment verified\. Quick Forecast validation is the next step\./);
  assert.match(panel, /Quick Forecast remains pending and has not started/);
  assert.doesNotMatch([panel, workflow].join("\n"), /startQuickForecast|workflowMode:\s*"quick_forecast"|router\.(?:push|replace)|location\.(?:assign|replace)|\/dashboard/);
  assert.doesNotMatch(workflow, /step:\s*"quick_forecast"/);
});

test("focused handoff test and browser implementation do not write accepted runtime", () => {
  assert.doesNotMatch(import.meta.url, /runtime[\\/]deployments/);
  assert.doesNotMatch(panel, /node:fs|runtimeRoot|writeFile|mkdir|execFile/);
  assert.doesNotMatch(workflow, /node:fs|DENGUEOPS_RUNTIME_ROOT/);
});
