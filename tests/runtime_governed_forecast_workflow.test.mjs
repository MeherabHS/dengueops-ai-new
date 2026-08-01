import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { require as tsxRequire } from "tsx/cjs/api";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const suitabilityModule = tsxRequire("../components/forecast/ModelSuitabilitySummary.tsx", import.meta.url);
const approvedForecastModule = tsxRequire("../components/forecast/ApprovedForecastPanel.tsx", import.meta.url);
const forecastWorkflowModule = tsxRequire("../components/forecast/ForecastRunWorkflow.tsx", import.meta.url);
const datasetValidationModule = tsxRequire("../components/forecast/DatasetValidationSummary.tsx", import.meta.url);
const { friendlyWinnerSelectionReason } = suitabilityModule;
const { runQualificationStartOnce } = approvedForecastModule;
const { isAssessmentValidationReady, isRetainedAssessmentComplete, runValidationStartOnce } = forecastWorkflowModule;
const DatasetValidationSummary = datasetValidationModule.default;
const [
  workflow,
  approval,
  approvedForecast,
  quickRun,
  leaderboard,
  stepper,
  validation,
  page,
  quickOption,
  contracts,
  client,
  jobRoute,
  assessmentRoute,
  labels,
] = await Promise.all([
  read("components/forecast/ForecastRunWorkflow.tsx"),
  read("components/forecast/ApprovalPanel.tsx"),
  read("components/forecast/ApprovedForecastPanel.tsx"),
  read("components/forecast/QuickForecastRunPanel.tsx"),
  read("components/forecast/ModelLeaderboard.tsx"),
  read("components/forecast/ForecastRunStepper.tsx"),
  read("components/forecast/DatasetValidationSummary.tsx"),
  read("app/forecast/page.tsx"),
  read("components/forecast/QuickForecastOption.tsx"),
  read("lib/runtime/contracts.ts"),
  read("lib/runtime/client.ts"),
  read("app/api/runtime/jobs/[jobId]/route.ts"),
  read("app/api/runtime/assessments/[assessmentId]/route.ts"),
  read("lib/status-labels.ts"),
]);

const previewFiles = {
  dengue: { missingColumns: [] },
  climate: { missingColumns: [] },
};

const renderAssessmentValidation = (serverValidation) => renderToStaticMarkup(createElement(DatasetValidationSummary, {
  files: previewFiles,
  mode: "assess_dataset",
  serverValidation,
  onMode: () => undefined,
  onValidate: () => undefined,
  revalidationRequired: false,
}));

test("assessment validation has one authoritative mutation action and no Assess Dataset control", () => {
  const html = renderAssessmentValidation({ status: "idle" });
  assert.match(html, /Local preview complete/);
  assert.match(html, /Row content has not been governed or accepted/);
  assert.match(html, /Authoritative dataset validation/);
  assert.match(html, /Validate the uploaded dengue and climate datasets against the governed assessment requirements before model assessment begins/);
  assert.equal((html.match(/>Validate datasets<\/button>/g) ?? []).length, 1);
  assert.doesNotMatch(html, /Assess Dataset/);
});

test("assignment completion exposes three distinct recurring workflow actions", () => {
  for (const label of [
    "Run forecast with assessed dataset",
    "Forecast with newer data",
    "Reassess models with updated data",
  ]) assert.equal((workflow.match(new RegExp(label, "g")) ?? []).length, 1);
  assert.match(workflow, /href="\/forecast\/run\?source=assessed"/);
  assert.match(workflow, /href="\/forecast\/run\?source=new"/);
  assert.match(workflow, /href="\/forecast\?intent=reassess"/);
  assert.doesNotMatch(workflow, />Use newer datasets<\/Link>/);
  assert.match(workflow, /The current assignment remains active until another governed assignment is successfully published/);
});

test("explicit reassessment starts clean at Upload without any authority mutation", () => {
  assert.match(page, /query\.intent === "reassess"/);
  assert.match(page, /entryIntent=\{entryIntent\}/);
  assert.match(page, /Upload updated labelled dengue and climate history/);
  const recovery = workflow.slice(workflow.indexOf("useEffect(() => {\n    if (recoveryStarted"), workflow.indexOf("const setFile"));
  assert.match(recovery, /entryIntent === "reassess"/);
  assert.match(recovery, /localStorage\.removeItem\(STORAGE_KEY\)/);
  assert.match(recovery, /window\.history\.replaceState\(window\.history\.state, "", "\/forecast"\)/);
  assert.ok(recovery.indexOf('entryIntent === "reassess"') < recovery.indexOf("localStorage.getItem(STORAGE_KEY)"));
  assert.doesNotMatch(recovery, /startDatasetAssessment|recordAssessmentDecision|startApprovedForecast|startModelAssignment|validateRuntimeDatasets|startQuickForecast|signOut|sessionStorage/);
});

test("terminal assessment recovery is rejected while nonterminal recovery remains available", () => {
  const current = {
    ok: true,
    status: "assigned",
    assignmentId: "11111111-1111-4111-8111-111111111111",
    selectedCandidateId: "gradient_boosting",
    selectedCandidateLabel: "Gradient boosting",
    assignmentCommitSha256: "a".repeat(64),
    assignmentPointerSha256: "b".repeat(64),
    sourceApprovedForecastRunId: "22222222-2222-4222-8222-222222222222",
    createdAt: "2026-08-02T00:00:00.000Z",
  };
  assert.equal(isRetainedAssessmentComplete({ status: "assigned_verified", current }), true);
  assert.equal(isRetainedAssessmentComplete({ status: "publishing", current }), false);
  assert.equal(isRetainedAssessmentComplete(undefined), false);
  const recovery = workflow.slice(workflow.indexOf("useEffect(() => {\n    if (recoveryStarted"), workflow.indexOf("const setFile"));
  assert.match(recovery, /isRetainedAssessmentComplete\(retained\.assignment\)/);
  assert.match(recovery, /loadCommittedAssessment\(assessmentId\)/);
  assert.match(recovery, /pollAssessment\(assessmentJobId, assessmentId\)/);
});

test("pending assessment validation is accessible, disabled, and guarded against duplicate POSTs", async () => {
  const html = renderAssessmentValidation({ status: "submitting" });
  assert.match(html, /<button[^>]*disabled=""[^>]*>Validating datasets…<\/button>/);
  assert.match(html, /animate-spin/);
  assert.match(html, /Validating datasets…/);
  assert.match(html, /0s elapsed/);

  let resolveValidation;
  let validationPosts = 0;
  const pending = new Promise((resolve) => { resolveValidation = resolve; });
  const guard = { current: false };
  const postValidation = () => {
    validationPosts += 1;
    return pending;
  };
  const first = runValidationStartOnce(guard, postValidation);
  const duplicate = runValidationStartOnce(guard, postValidation);
  assert.equal(validationPosts, 1);
  assert.equal(guard.current, true);
  resolveValidation({ ok: true });
  assert.deepEqual(await first, { ok: true });
  assert.equal(await duplicate, null);
  assert.equal(guard.current, false);
});

test("assessment continuation requires successful authoritative validation", () => {
  const eligibleResponse = {
    status: "ready",
    response: { eligibility: { assessDataset: { assessmentStatus: "full_assessment_eligible" } } },
  };
  assert.equal(isAssessmentValidationReady({ status: "idle" }, null), false);
  assert.equal(isAssessmentValidationReady(eligibleResponse, null), false);
  assert.equal(isAssessmentValidationReady(eligibleResponse, "assess_dataset"), true);
  assert.equal(isAssessmentValidationReady({ status: "failed", error: {} }, "assess_dataset"), false);
});

test("assessment workflow owns assess_dataset mode and separates continuation from assessment mutation", () => {
  assert.match(workflow, /const initial:[\s\S]*?mode: "assess_dataset"/);
  assert.match(workflow, /workflowMode: "assess_dataset"/);
  const continuation = workflow.slice(workflow.indexOf("Continue to assessment") - 260, workflow.indexOf("Continue to assessment") + 80);
  assert.match(continuation, /disabled=\{!assessmentReady\}/);
  assert.match(continuation, /step: "assessment"/);
  assert.doesNotMatch(continuation, /runAssessment|startDatasetAssessment/);
  assert.match(workflow, /Start model assessment/);
});

test("authoritative validation failures remain visible without enabling continuation", () => {
  const html = renderAssessmentValidation({
    status: "failed",
    error: {
      code: "validation_request_failed",
      category: "internal",
      message: "The runtime Python executable is not configured.",
      retryable: true,
      correlationId: "not-available",
    },
  });
  assert.match(html, /Validation service failed/);
  assert.match(html, /The runtime Python executable is not configured\./);
  assert.match(html, /Reference: not-available/);
  assert.equal(isAssessmentValidationReady({ status: "failed", error: {} }, "assess_dataset"), false);
});

test("technical winner is assessment-derived and is the bounded default decision", () => {
  assert.match(approval, /assessment\.technicalWinnerModelId/);
  assert.match(approval, /candidate\.status === "technical_winner"/);
  assert.match(approval, /Technical winner is the default path/);
  assert.match(approval, /technical winner.*dataset.*governed assessment/i);
  const winner = approval.slice(approval.indexOf("const submitWinner"), approval.indexOf("const submitOverride"));
  assert.match(winner, /decision: "approve_technical_winner"/);
  assert.match(winner, /expectedAssessmentSummarySha256/);
  assert.match(winner, /boundedWinnerNote \|\| DEFAULT_TECHNICAL_WINNER_REASON/);
  assert.match(winner, /uncertaintyLimitationsAcknowledged: true/);
  assert.doesNotMatch(winner, /selectedModelId/);
  assert.doesNotMatch(winner, /MIN_REASON_LENGTH|overrideReasonValid/);
  assert.match(approval, /Optional audit note/);
  assert.match(approval, /Technical winner approved based on the verified governed assessment ranking\./);
});

test("technical winner reason replaces only the exact raw winner token", () => {
  const raw = "poisson_gam was the best-performing eligible learned model within this governed assessment.";
  assert.equal(
    friendlyWinnerSelectionReason(raw, "poisson_gam"),
    "Poisson GAM was the best-performing eligible learned model within this governed assessment.",
  );
  assert.equal(friendlyWinnerSelectionReason("not_poisson_gam_extra remains technical.", "poisson_gam"), "not_poisson_gam_extra remains technical.");
  assert.match(leaderboard, /Candidate ID[\s\S]*candidate\.modelId/);
});

test("qualification initiating guard is synchronous while the POST is unresolved", async () => {
  let resolveStart;
  let postCalls = 0;
  const startingStates = [];
  const deferred = new Promise((resolve) => { resolveStart = resolve; });
  const guard = { current: false };
  const operation = () => {
    postCalls += 1;
    return deferred;
  };
  const first = runQualificationStartOnce(guard, (value) => startingStates.push(value), operation);
  const second = runQualificationStartOnce(guard, (value) => startingStates.push(value), operation);
  assert.equal(postCalls, 1);
  assert.equal(guard.current, true);
  assert.deepEqual(startingStates, [true]);
  resolveStart({ ok: true, status: "queued" });
  assert.deepEqual(await first, { ok: true, status: "queued" });
  assert.equal(await second, null);
  assert.equal(guard.current, false);
  assert.deepEqual(startingStates, [true, false]);
});

test("governed override is explicit and contains only verified eligible non-winners", () => {
  assert.match(approval, /overrideOpen/);
  assert.match(approval, /Use governed expert override/);
  assert.match(approval, /candidate\.status === "eligible_non_winner"/);
  assert.match(approval, /candidate\.candidateClass === "learned_model"/);
  assert.match(approval, /candidate\.completionStatus === "complete"/);
  assert.match(approval, /candidate\.failedFolds === 0/);
  assert.match(approval, /candidate\.deployableForOneRun/);
  assert.match(approval, /<select id="governed-override-candidate"/);
  assert.match(approval, /Select eligible alternative/);
  assert.match(approval, /Override justification \*/);
  assert.match(approval, /Approve governed override/);
  assert.doesNotMatch(approval, /name=["']selectedModelId|placeholder=.*model.*id/i);
  const overrideStart = approval.indexOf("const submitOverride");
  const override = approval.slice(overrideStart, approval.indexOf("return <section", overrideStart));
  for (const marker of [
    'decision: "approve_eligible_non_winner"',
    "expectedAssessmentSummarySha256",
    "selectedModelId:",
    "technicalWinnerNotSelectedAcknowledged: true",
    "uncertaintyLimitationsAcknowledged: true",
  ]) assert.match(override, new RegExp(marker));
});

test("override reason and acknowledgements are bounded and duplicate publication is blocked", () => {
  assert.match(approval, /MIN_REASON_LENGTH = 12/);
  assert.match(approval, /MAX_REASON_LENGTH = 1000/);
  assert.match(approval, /overrideReasonValid/);
  assert.match(approval, /winnerNotSelectedAcknowledged/);
  assert.match(approval, /uncertaintyAcknowledged/);
  assert.match(approval, /setSelectedOverride\(null\)/);
  assert.match(approval, /setOverrideReason\(""\)/);
  assert.match(workflow, /decisionAction\.current/);
  assert.match(workflow, /if \(!state\.assessment \|\| recordedDecision \|\| decisionAction\.current\) return/);
  assert.match(approval, /Governed model decision recorded/);
});

test("ranking renders every returned candidate without hardcoded candidate count", () => {
  assert.match(leaderboard, /assessment\.workflow\.candidates/);
  assert.match(leaderboard, /candidates\.map/);
  assert.match(leaderboard, /candidate\.successfulFolds\} \/ \{requiredFolds\}/);
  assert.match(leaderboard, /candidate\.failedFolds\} failed/);
  for (const marker of ["displayRank", "modelLabel", "modelFamily", "successfulFolds", "plannedFoldCount", "mae", "rmse", "wape", "candidateClass", "Technical winner", "Eligible override", "candidate.reasons"]) {
    assert.match(leaderboard, new RegExp(marker.replace(".", "\\.")));
  }
  assert.doesNotMatch([leaderboard, validation].join("\n"), /seven governed candidates/i);
  assert.match(leaderboard, /modelLabel\(candidate\.modelId\)/);
  for (const candidate of ["moving_average_4w", "seasonal_naive_52w", "ridge_regression", "poisson_regression", "random_forest", "gradient_boosting", "elastic_net", "negative_binomial_regression", "extra_trees", "hist_gradient_boosting", "poisson_gam"]) {
    assert.match(contracts, new RegExp(candidate));
  }
  assert.match(labels, /return governedModelLabel\(value\) \?\? statusLabel\(value\)/);
  assert.match(leaderboard, /primaryCandidateStatusLabel/);
  assert.match(leaderboard, /Evaluation only/);
  assert.match(leaderboard, /candidateClass !== "learned_model"/);
  assert.doesNotMatch(leaderboard, /baseline[\s\S]{0,120}Eligible override/);
});

test("existing server-generated MSE and R-squared render only as secondary diagnostics", () => {
  assert.match(contracts, /mse\?: number \| null/);
  assert.match(contracts, /r2\?: number \| null/);
  assert.match(leaderboard, /MSE and R² are secondary diagnostics/);
  for (const metricName of ["mae", "mse", "rmse", "wape", "r2"]) {
    assert.match(leaderboard, new RegExp(`candidate\\.metrics\\?\\.${metricName}`));
  }
  for (const label of ["MAE", "RMSE", "WAPE", "MSE", "R²"]) assert.match(leaderboard, new RegExp(`"${label}"`));
  assert.match(leaderboard, /value == null \? "Not available" : `\$\{value\.toFixed\(2\)\}\$\{suffix\}`/);
  assert.doesNotMatch(leaderboard, /metrics\?\.rmse\s*\*\s*candidate\.metrics\?\.rmse|Math\.pow\([^)]*rmse|Math\.(?:max|min)\([^)]*r2/);
  assert.doesNotMatch(leaderboard, /\bMAPE\b/i);
  const serverDiagnosticFixture = { mse: 4.25, r2: -0.375 };
  assert.equal(serverDiagnosticFixture.mse.toFixed(2), "4.25");
  assert.equal(serverDiagnosticFixture.r2.toFixed(2), "-0.38");
  assert.equal((null ?? "Not available"), "Not available");
});

test("approved forecast sends no model identity, polls the returned job URL, and cannot start twice", () => {
  const generate = approvedForecast.slice(approvedForecast.indexOf("const generate"), approvedForecast.indexOf("return <section"));
  assert.match(generate, /expectedDecisionCommitSha256: decision\.decisionCommitSha256/);
  const requestCall = generate.slice(generate.indexOf("startApprovedForecast"), generate.indexOf("if (!started.ok)"));
  assert.doesNotMatch(requestCall, /selectedModelId|modelId/);
  assert.match(generate, /getRuntimeJobByStatusUrl\(started\.statusUrl\)/);
  assert.match(approvedForecast, /polling\.current/);
  assert.match(approvedForecast, /runQualificationStartOnce/);
  assert.match(approvedForecast, /startingRef/);
  assert.match(approvedForecast, /state\.status !== "idle"/);
  assert.match(client, /fetch\(statusUrl, \{ cache: "no-store" \}\)/);
});

test("qualification completion stays on governance workflow and assignment completes it", () => {
  assert.match(approvedForecast, /Ready for governed assignment/);
  assert.match(approvedForecast, /approvedForecastCommitSha256/);
  assert.match(approvedForecast, /committedRunId/);
  assert.match(approvedForecast, /sourceDecisionId/);
  const approvedStage = workflow.slice(workflow.indexOf('state.step === "qualification_run"'), workflow.indexOf('state.step === "assignment"'));
  assert.doesNotMatch([approvedStage, approvedForecast].join("\n"), /location\.assign|router\.(?:push|replace)|href="\/dashboard"|startQuickForecast/);
  for (const label of ["Upload", "Validation", "Assessment", "Ranking", "Decision", "Qualification run", "Assignment", "Complete"]) assert.match(stepper, new RegExp(label));
  const governanceStages = stepper.slice(stepper.indexOf("const governanceSteps"), stepper.indexOf("const operationalSteps"));
  assert.doesNotMatch(governanceStages, /Quick Forecast/);
  assert.match(stepper, /data-stage-state/);
  assert.doesNotMatch(workflow, /QuickForecastOption|QuickForecastRunPanel/);
});

test("Quick Forecast dashboard handoff requires the exact verified current run", () => {
  assert.match(quickRun, /job\.committedRunId !== expectedRunId/);
  assert.match(quickRun, /latest\.runId === committedRunId/);
  assert.match(quickRun, /latest\.dashboard\.latestRun\.runId === committedRunId/);
  assert.match(quickRun, /status: "current_verified"/);
  const navigation = quickRun.slice(quickRun.indexOf('state.status !== "current_verified"'), quickRun.indexOf("const terminalFailure"));
  assert.match(navigation, /state\.exactCurrentRunId !== state\.committedRunId/);
  assert.match(navigation, /state\.committedRunId !== state\.expectedRunId/);
  assert.match(navigation, /router\.push\("\/dashboard"\)/);
});

test("refresh recovery resumes GET polling but never repeats append-only actions", () => {
  assert.match(workflow, /localStorage\.getItem\(STORAGE_KEY\)/);
  assert.match(workflow, /retainedAssessmentId/);
  assert.match(workflow, /assessmentJobId/);
  assert.match(workflow, /approvedForecast/);
  assert.match(workflow, /getDatasetAssessment/);
  assert.match(workflow, /getRuntimeJob\(jobId\)/);
  const recovery = workflow.slice(workflow.indexOf("useEffect(() => {\n    if (recoveryStarted"), workflow.indexOf("const setFile"));
  assert.doesNotMatch(recovery, /recordAssessmentDecision|startApprovedForecast|startDatasetAssessment/);
});

test("completed job route exposes only a server-verified approved forecast commit hash", () => {
  assert.match(jobRoute, /job\.status !== "completed"/);
  assert.match(jobRoute, /readVerifiedDecision/);
  assert.match(jobRoute, /decision\.committedRunId !== job\.committedRunId/);
  assert.match(jobRoute, /decision\.decisionCommitSha256 !== job\.decisionCommitSha256/);
  for (const binding of ["commit.runId", "commit.decisionId", "commit.assessmentId", "commit.authorizationId", "commit.selectedModelId"]) assert.match(jobRoute, new RegExp(binding.replace(".", "\\.")));
  for (const binding of ["commit.jobId", "commit.datasetId", "commit.deploymentId", "commit.decisionCommitSha256", "commit.assessmentCommitSha256", "commit.selectedModelParameterSha256"]) assert.match(jobRoute, new RegExp(binding.replace(".", "\\.")));
  assert.match(jobRoute, /commit\.workflowMode !== "approved_assessment_forecast"/);
  assert.match(jobRoute, /commit\.completeReconciliation !== true/);
  assert.match(jobRoute, /approvedForecastCommitSha256: await verifiedApprovedForecastCommitSha256/);
  assert.match(jobRoute, /sha256\(bytes\)/);
  assert.doesNotMatch(jobRoute, /expectedApprovedForecastCommitSha256|body\.approvedForecast|request\.json/);
  assert.match(contracts, /status:"completed";committedRunId:string;approvedForecastCommitSha256:string/);
});

test("assessment detail explicitly resolves p2-v2 and p2-v3 through current assignment authority", () => {
  const resolver = assessmentRoute.slice(
    assessmentRoute.indexOf("switch (assessmentPolicy.policyVersion)"),
    assessmentRoute.indexOf("const policyIdentity"),
  );
  assert.match(resolver, /case "p2-v2":\s*case "p2-v3":\s*activeModel = await resolveActiveModel/);
  assert.match(resolver, /case "p1\.4d-1-v1":\s*case "p2-v1":\s*activeModel = await resolveHistoricalActiveModelP2V1/);
  assert.match(resolver, /default:\s*throw new RuntimePublicError\(\s*"unsupported_assessment_policy_identity"/);
});

test("active workflow has no stale fixed-model or obsolete decision copy", () => {
  const active = [page, workflow, approval, approvedForecast, leaderboard, validation, quickOption].join("\n");
  for (const stale of [/Random Forest is approved/i, /Current approved model/i, /Keep current Random Forest/i, /seven governed candidates/i, /p2-v1 trusted-internal/i, /keep_current_model/, /reject_assessment/, /\bdefer\b/]) assert.doesNotMatch(active, stale);
});

test("focused tests are static and do not write accepted runtime", async () => {
  const ownSource = await read("tests/runtime_governed_forecast_workflow.test.mjs");
  assert.doesNotMatch(ownSource, /import\s*\{[^}]*\b(writeFile|mkdir|rm)\b[^}]*\}\s*from\s*["']node:fs/);
  assert.doesNotMatch(ownSource, /process\.env\.(?:RUNTIME_ROOT|DENGUEOPS_RUNTIME_ROOT)/);
});
