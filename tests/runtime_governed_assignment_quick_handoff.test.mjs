import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [panel, quickPanel, workflow, validationSummary, client, contracts, route, validationRoute, quickRoute] = await Promise.all([
  read("components/forecast/ModelAssignmentPanel.tsx"),
  read("components/forecast/QuickForecastRunPanel.tsx"),
  read("components/forecast/ForecastRunWorkflow.tsx"),
  read("components/forecast/DatasetValidationSummary.tsx"),
  read("lib/runtime/client.ts"),
  read("lib/runtime/contracts.ts"),
  read("app/api/runtime/model-assignments/route.ts"),
  read("app/api/runtime/validate/route.ts"),
  read("app/api/runtime/runs/quick/route.ts"),
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

test("verified assignment and fresh validation gate the deliberate Quick Forecast action", () => {
  assert.match(panel, /Governed assignment verified\. Quick Forecast validation is the next step\./);
  assert.match(workflow, /assignment\.status !== "assigned_verified" \|\| !assignment\.current/);
  assert.match(workflow, /step: "quick_forecast"/);
  assert.match(workflow, /Quick Forecast validation ready\. Forecast execution is the next step\./);
  assert.match(workflow, /state\.quickValidation\.status === "quick_validation_ready"[\s\S]*<QuickForecastRunPanel/);
  assert.match(quickPanel, /Run Quick Forecast/);
  assert.match(quickPanel, /state\.status !== "ready_to_run"/);
});

test("assessment workspace and validation evidence are reset without erasing governed evidence", () => {
  const transition = workflow.slice(workflow.indexOf('step: "quick_forecast"'), workflow.indexOf("Fresh Quick Forecast validation is now available"));
  for (const marker of [
    'mode: "quick_forecast"',
    'serverValidation: { status: "idle" }',
    "workspaceId:",
    "datasetId:",
    "job: null",
    "result: null",
    "assignment,",
  ]) assert.match(transition, new RegExp(marker));
  assert.doesNotMatch(transition, /assessment:\s*null|approval:\s*null|approvedForecast:\s*empty/);
});

test("same-page files are reused only after a deliberate guarded action", () => {
  assert.match(workflow, /fileSource: retainedFilesAvailable \? "retained" : null/);
  assert.match(workflow, /Reuse uploaded files and validate for Quick Forecast/);
  assert.match(workflow, /quickValidationAction\.current/);
  assert.match(workflow, /quickValidationAction\.current = true/);
  assert.equal((workflow.match(/validateRuntimeDatasets\(\{/g) ?? []).length, 2);
  assert.doesNotMatch(workflow.slice(workflow.indexOf("onStateChange={(assignment)"), workflow.indexOf("Fresh Quick Forecast validation is now available")), /validateRuntimeDatasets/);
});

test("missing retained files require both datasets to be selected again", () => {
  assert.match(workflow, /files: retainedFilesAvailable \? current\.files : \{\}/);
  assert.match(workflow, /status: retainedFilesAvailable \? "quick_files_reuse_available" : "quick_files_required"/);
  assert.match(workflow, /The original files are no longer available in this browser session/);
  assert.match(workflow, /Select both datasets again/);
  assert.match(workflow, /kind="dengue"[\s\S]*kind="climate"/);
  assert.doesNotMatch(workflow, /new File\(|demo|bundled data/i);
});

test("fresh validation multipart request contains only governed validation inputs", () => {
  const quickValidation = workflow.slice(workflow.indexOf("const validateQuickForecast"), workflow.indexOf("const runAssessment"));
  for (const marker of [
    "dengueFile:",
    "climateFile:",
    'deploymentId: "dhaka_south"',
    'workflowMode: "quick_forecast"',
  ]) assert.match(quickValidation, new RegExp(marker));
  assert.doesNotMatch(quickValidation.slice(quickValidation.indexOf("validateRuntimeDatasets"), quickValidation.indexOf("if (!response.ok)")), /modelId:|candidateId:|assignmentId:|assessmentWorkspaceId|pointerContents|approvedForecastRunId/);
  assert.match(client, /form\.append\("dengueFile"/);
  assert.match(client, /form\.append\("climateFile"/);
  assert.match(client, /form\.append\("deploymentId"/);
  assert.match(client, /form\.append\("workflowMode"/);
});

test("fresh validation requires ready quick mode, eligibility, and exact assignment binding", () => {
  const quickValidation = workflow.slice(workflow.indexOf("const validateQuickForecast"), workflow.indexOf("const runAssessment"));
  for (const marker of [
    'response.status === "ready"',
    'response.workflowMode === "quick_forecast"',
    'response.deploymentId === "dhaka_south"',
    "response.eligibility.quickForecast.eligible",
    "authority.assignmentId === verifiedAssignment.assignmentId",
    "authority.authoritySnapshotSha256 === verifiedAssignment.assignmentPointerSha256",
    "authority.modelId === verifiedAssignment.selectedCandidateId",
  ]) assert.match(quickValidation, new RegExp(marker.replaceAll(".", "\\.")));
  assert.match(quickValidation, /validationRecordSha256: response\.validationRecordSha256/);
  assert.match(quickValidation, /status: "quick_validation_ready"/);
});

test("assignment mismatch fails closed, refreshes current authority, and never retries validation", () => {
  const quickValidation = workflow.slice(workflow.indexOf("const validateQuickForecast"), workflow.indexOf("const runAssessment"));
  assert.match(quickValidation, /const refreshed = await getCurrentModelAssignment\(\)/);
  assert.match(quickValidation, /status: "quick_assignment_conflict"/);
  assert.match(quickValidation, /errorCode: "assignment_pointer_conflict"/);
  assert.match(workflow, /Validation was not retried and no Quick Forecast job was created/);
  assert.equal((quickValidation.match(/validateRuntimeDatasets\(\{/g) ?? []).length, 1);
});

test("validation route verifies artifact mode instead of echoing the form field", () => {
  assert.match(validationRoute, /const verifiedWorkflowMode = validation\.workflowMode/);
  assert.match(validationRoute, /verifiedWorkflowMode !== workflowMode/);
  assert.match(validationRoute, /workflowMode: verifiedWorkflowMode/);
  assert.doesNotMatch(validationRoute, /workflowMode:\s*workflowMode,/);
});

test("all explicit Quick validation states and dynamic summary evidence are present", () => {
  for (const state of [
    "quick_validation_pending",
    "quick_files_reuse_available",
    "quick_files_required",
    "quick_validation_running",
    "quick_validation_ready",
    "quick_validation_failed",
    "quick_assignment_conflict",
  ]) assert.match(contracts + workflow, new RegExp(state));
  for (const label of [
    "Fresh Quick Forecast validation",
    "New workspace created",
    "Dataset identity",
    "Current governed assignment",
    "Assignment binding",
    "Quick Forecast eligibility",
  ]) assert.match(validationSummary, new RegExp(label));
});

test("successful validation does not start a job, redirect, or publish forecast authority", () => {
  const validationAction = workflow.slice(workflow.indexOf("const validateQuickForecast"), workflow.indexOf("const runAssessment"));
  assert.doesNotMatch(validationAction, /startQuickForecast|\/api\/runtime\/runs\/quick|router\.(?:push|replace)|location\.(?:assign|replace)|\/dashboard/);
  assert.doesNotMatch(validationRoute, /forecast\/latest|write.*pointer|startQuickForecast/);
  assert.match(workflow, /quickForecast: emptyQuickForecast/);
});

test("Quick Forecast request uses only validated identities and the verified assignment pointer", () => {
  const request = quickPanel.slice(quickPanel.indexOf("const request:"), quickPanel.indexOf("useEffect(() => () =>"));
  for (const marker of [
    "workspaceId: validation.workspaceId",
    "datasetId: validation.datasetId",
    "deploymentId: validation.deploymentId",
    "validationRecordSha256: validation.validationRecordSha256",
    "expectedAssignmentPointerSha256: assignment.assignmentPointerSha256",
  ]) assert.match(request, new RegExp(marker.replaceAll(".", "\\.")));
  assert.doesNotMatch(request, /modelId|candidateId|selectedCandidateId|assignmentId|assessmentId|decisionId|pointerContent/);
  assert.match(quickRoute, /authority\.authoritySnapshotSha256 !== body\.expectedAssignmentPointerSha256/);
});

test("duplicate clicks and assignment conflicts cannot create an automatic retry", () => {
  assert.match(quickPanel, /starting\.current/);
  assert.match(quickPanel, /starting\.current = true/);
  assert.equal((quickPanel.match(/startQuickForecast\(request\)/g) ?? []).length, 1);
  assert.match(quickPanel, /response\.error\.code === "quick_forecast_assignment_conflict"/);
  assert.match(quickPanel, /onAssignmentConflict\(\)/);
  assert.match(workflow, /step: "assignment"/);
  assert.match(workflow, /status: "loading_current_assignment"/);
  const conflictBranch = quickPanel.slice(quickPanel.indexOf('response.error.code === "quick_forecast_assignment_conflict"'), quickPanel.indexOf('response.error.code === "quick_forecast_publication_in_progress"'));
  assert.doesNotMatch(conflictBranch, /startQuickForecast|recoverQuickForecastStart/);
});

test("exclusive-marker recovery resumes the same bounded job polling contract", () => {
  assert.match(quickRoute, /readStartMarker/);
  assert.match(quickRoute, /verifyMarkerBindings/);
  assert.match(quickRoute, /readVisibleQuickJob/);
  assert.match(quickRoute, /verifyRecoveredJob/);
  assert.match(quickRoute, /successResponse\(existing, authority, status, true\)/);
  assert.match(quickPanel, /response\.recovered \? "recovering_existing_job"/);
  assert.match(quickPanel, /getRuntimeJobByStatusUrl\(statusUrl\)/);
});

test("job polling handles bounded states and requires exact committed run identity", () => {
  assert.match(quickPanel, /polling\.current/);
  assert.match(quickPanel, /JOB_POLL_INITIAL_MS = 1500/);
  assert.match(quickPanel, /JOB_POLL_MAX_MS = 5000/);
  for (const status of ["queued", "running", "job_failed", "job_cancelled", "job_timed_out"]) assert.match(quickPanel, new RegExp(status));
  assert.match(quickPanel, /job\.jobKind !== "quick_forecast"/);
  assert.match(quickPanel, /!job\.committedRunId \|\| job\.committedRunId !== expectedRunId/);
  assert.match(quickPanel, /authority\.assignmentId !== assignment\.assignmentId/);
  assert.match(quickPanel, /authority\.authoritySnapshotSha256 !== assignment\.assignmentPointerSha256/);
});

test("Quick Forecast panel exposes every bounded execution and handoff state", () => {
  for (const status of [
    "ready_to_run",
    "starting",
    "queued",
    "running",
    "recovering_existing_job",
    "publication_in_progress",
    "assignment_conflict",
    "job_failed",
    "job_cancelled",
    "job_timed_out",
    "committed_pending_current_verification",
    "current_verification_pending",
    "current_verification_timeout",
    "current_verified",
    "authentication_required",
    "failed_uncertain",
  ]) assert.match(contracts + quickPanel, new RegExp(status));
});

test("job completion alone never redirects and exact current run controls dashboard handoff", () => {
  const completed = quickPanel.slice(quickPanel.indexOf('job.status === "completed"'), quickPanel.indexOf('job.status === "failed"'));
  assert.match(completed, /committed_pending_current_verification/);
  assert.match(completed, /verifyCurrentForecast/);
  assert.doesNotMatch(completed, /router\.push/);
  for (const condition of [
    'latest.sourceType === "uploaded"',
    "latest.runId === committedRunId",
    "committedRunId === expectedRunId",
    "latest.dashboard.latestRun.runId === committedRunId",
    'latest.dashboard.modelUse.workflowMode === "quick_forecast"',
  ]) assert.match(quickPanel, new RegExp(condition.replaceAll(".", "\\.")));
  assert.match(quickPanel, /state\.status !== "current_verified"/);
  assert.match(quickPanel, /state\.exactCurrentRunId !== state\.committedRunId/);
  assert.match(quickPanel, /router\.push\("\/dashboard"\)/);
});

test("current verification is read-only, bounded, and retry never reruns Quick Forecast", () => {
  assert.match(quickPanel, /CURRENT_VERIFY_INITIAL_MS = 1500/);
  assert.match(quickPanel, /CURRENT_VERIFY_MAX_MS = 5000/);
  assert.match(quickPanel, /CURRENT_VERIFY_MAX_TOTAL_MS = 30_000/);
  assert.match(quickPanel, /Math\.min\(CURRENT_VERIFY_MAX_MS, Math\.round\(delay \* 1\.6\)\)/);
  assert.match(quickPanel, /current_verification_timeout/);
  const retry = quickPanel.slice(quickPanel.indexOf('state.status === "current_verification_timeout"'), quickPanel.indexOf("Open dashboard"));
  assert.match(retry, /verifyCurrentForecast/);
  assert.doesNotMatch(retry, /startQuickForecast|recoverQuickForecastStart/);
});

test("refresh retains bounded job identifiers but rechecks job and current authority", () => {
  assert.match(workflow, /quickForecast\?: Partial<QuickForecastWorkflowState>/);
  assert.match(workflow, /boundedRetainedQuickForecast/);
  assert.match(workflow, /status: "recovering_existing_job"/);
  assert.match(quickPanel, /resumedJobKey/);
  assert.match(quickPanel, /void pollJob\(state\.jobId, state\.expectedRunId, state\.statusUrl\)/);
  assert.match(quickPanel, /activeModelAuthority/);
  assert.match(quickPanel, /getLatestDashboard\("dhaka_south"\)/);
  assert.doesNotMatch(quickPanel, /currentVerified.*localStorage|localStorage.*currentVerified/);
});

test("focused handoff test and browser implementation do not write accepted runtime", () => {
  assert.doesNotMatch(import.meta.url, /runtime[\\/]deployments/);
  assert.doesNotMatch(panel, /node:fs|runtimeRoot|writeFile|mkdir|execFile/);
  assert.doesNotMatch(workflow, /node:fs|DENGUEOPS_RUNTIME_ROOT/);
  assert.doesNotMatch(quickPanel, /node:fs|DENGUEOPS_RUNTIME_ROOT|writeFile|mkdir/);
});
