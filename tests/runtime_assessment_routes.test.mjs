import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("assessment start accepts identities only and queues without executing Python", async () => {
  const source = await read("app/api/runtime/assessments/route.ts");
  assert.match(source, /export const runtime = "nodejs"/);
  assert.match(source, /workspaceId.*datasetId.*deploymentId.*validationRecordSha256/s);
  assert.match(source, /unexpected_assessment_field/);
  assert.match(source, /full_assessment_eligible/);
  assert.match(source, /p2-v1/);
  assert.match(source, /minimumFoldCount/);
  assert.match(source, /maximumFoldCount/);
  assert.match(source, /plannedFoldCount !== Math\.min\(availableFoldCount, 68\)/);
  assert.doesNotMatch(source, /labelledRows\s*!==\s*173|availableFoldCount\s*!==\s*68/);
  assert.doesNotMatch(source, /spawn\(|exec\(|candidateIds\s*:|technicalWinner\s*:/);
});

test("assessment result is compact, hash-verified, and no-store", async () => {
  const source = await read("app/api/runtime/assessments/[assessmentId]/route.ts");
  assert.match(source, /readVerifiedAssessment/);
  assert.match(source, /assessmentSummarySha256/);
  assert.match(source, /Cache-Control.*no-store/s);
  assert.doesNotMatch(source, /rolling_validation\.json|uploaded rows|stdout\.log/);
});

test("assessment result adds governed order and redacted workflow state", async () => {
  const source = await read("app/api/runtime/assessments/[assessmentId]/route.ts");
  assert.match(source, /deriveAssessmentDisplayOrder/);
  assert.match(source, /displayRank/);
  assert.match(source, /technicalWinnerDeployable/);
  assert.match(source, /currentApprovedModel/);
  assert.match(source, /readVerifiedAssessmentDecisionState/);
  assert.match(source, /authorizationStatus/);
  assert.match(source, /committedRunId/);
  assert.match(source, /assessmentPolicy/);
  assert.match(source, /phase2_decision_policy_available/);
  assert.match(source, /loadDecisionPolicy/);
  assert.match(source, /plannedFoldCount/);
  assert.match(source, /selectedEvaluationPeriod/);
  assert.doesNotMatch(source, /operatorIdentifier|internalDecisionSecret|reason:/);
});

test("frontend assessment completion never refreshes Overview", async () => {
  const source = await read("components/forecast/ForecastRunWorkflow.tsx");
  assert.match(source, /startDatasetAssessment/);
  assert.match(source, /committedAssessmentId/);
  assert.match(source, /assessment_completed/);
  const assessmentBranch = source.slice(source.indexOf("const runAssessment"), source.indexOf("const recordDecision"));
  assert.doesNotMatch(assessmentBranch, /getLatestDashboard|location\.assign|sessionStorage/);
});
