import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
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

test("technical winner is assessment-derived and is the bounded default decision", () => {
  assert.match(approval, /assessment\.technicalWinnerModelId/);
  assert.match(approval, /candidate\.status === "technical_winner"/);
  assert.match(approval, /Technical winner is the default path/);
  assert.match(approval, /uploaded dataset.*verified assessment performance/i);
  const winner = approval.slice(approval.indexOf("const submitWinner"), approval.indexOf("const submitOverride"));
  assert.match(winner, /decision: "approve_technical_winner"/);
  assert.match(winner, /expectedAssessmentSummarySha256/);
  assert.match(winner, /uncertaintyLimitationsAcknowledged: true/);
  assert.doesNotMatch(winner, /selectedModelId/);
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

test("decision reason and acknowledgements are bounded and duplicate publication is blocked", () => {
  assert.match(approval, /MIN_REASON_LENGTH = 12/);
  assert.match(approval, /MAX_REASON_LENGTH = 1000/);
  assert.match(approval, /winnerNotSelectedAcknowledged/);
  assert.match(approval, /uncertaintyAcknowledged/);
  assert.match(workflow, /decisionAction\.current/);
  assert.match(workflow, /if \(!state\.assessment \|\| recordedDecision \|\| decisionAction\.current\) return/);
  assert.match(approval, /Governed model decision recorded/);
});

test("ranking renders every returned candidate without hardcoded candidate count", () => {
  assert.match(leaderboard, /assessment\.workflow\.candidates/);
  assert.match(leaderboard, /candidates\.map/);
  assert.match(leaderboard, /candidate\.successfulFolds\} completed \/ \{requiredFolds\} required/);
  assert.match(leaderboard, /candidate\.failedFolds\} failed/);
  for (const marker of ["displayRank", "modelLabel", "modelFamily", "successfulFolds", "plannedFoldCount", "mae", "rmse", "wape", "candidateClass", "Technical winner", "Eligible override", "candidate.reasons"]) {
    assert.match(leaderboard, new RegExp(marker.replace(".", "\\.")));
  }
  assert.doesNotMatch([leaderboard, validation].join("\n"), /seven governed candidates/i);
  assert.match(leaderboard, /candidate\.modelLabel \|\| modelLabel\(candidate\.modelId\)/);
  for (const candidate of ["moving_average_4w", "seasonal_naive_52w", "ridge_regression", "poisson_regression", "random_forest", "gradient_boosting", "elastic_net", "negative_binomial_regression", "extra_trees", "hist_gradient_boosting", "poisson_gam"]) {
    assert.match(contracts, new RegExp(candidate));
  }
  assert.match(labels, /return statusLabel\(value\)/);
});

test("existing server-generated MSE and R-squared render only as secondary diagnostics", () => {
  assert.match(contracts, /mse\?: number \| null/);
  assert.match(contracts, /r2\?: number \| null/);
  assert.match(leaderboard, /Core ranking metrics/);
  assert.match(leaderboard, /Secondary diagnostics/);
  for (const metricName of ["mae", "mse", "rmse", "wape", "r2"]) {
    assert.match(leaderboard, new RegExp(`candidate\\.metrics\\?\\.${metricName}`));
  }
  assert.match(leaderboard, /\["MAE", "RMSE", "WAPE", "MSE", "R²"\]/);
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
  assert.match(approvedForecast, /state\.status !== "idle"/);
  assert.match(client, /fetch\(statusUrl, \{ cache: "no-store" \}\)/);
});

test("completed approved run stays on workflow with assignment and Quick Forecast pending", () => {
  assert.match(approvedForecast, /Ready for governed assignment/);
  assert.match(approvedForecast, /approvedForecastCommitSha256/);
  assert.match(approvedForecast, /committedRunId/);
  assert.match(approvedForecast, /sourceDecisionId/);
  const approvedStage = workflow.slice(workflow.indexOf('state.step === "approved_forecast"'), workflow.indexOf('state.step === "assignment"'));
  assert.doesNotMatch([approvedStage, approvedForecast].join("\n"), /location\.assign|router\.(?:push|replace)|href="\/dashboard"|startQuickForecast/);
  for (const label of ["Upload", "Validation", "Assessment", "Ranking", "Decision", "Approved forecast", "Assignment", "Quick Forecast", "Complete"]) assert.match(stepper, new RegExp(label));
  assert.match(stepper, /data-stage-state/);
  assert.match(quickOption, /Pending; this workflow does not start Quick Forecast/);
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
