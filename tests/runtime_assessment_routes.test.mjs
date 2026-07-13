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
  assert.doesNotMatch(source, /spawn\(|exec\(|candidateIds\s*:|technicalWinner\s*:/);
});

test("assessment result is compact, hash-verified, and no-store", async () => {
  const source = await read("app/api/runtime/assessments/[assessmentId]/route.ts");
  assert.match(source, /artifactHashes/);
  assert.match(source, /Cache-Control.*no-store/s);
  assert.doesNotMatch(source, /rolling_validation\.json|uploaded rows|stdout\.log/);
});

test("frontend assessment completion never refreshes Overview", async () => {
  const source = await read("components/forecast/ForecastRunWorkflow.tsx");
  assert.match(source, /startDatasetAssessment/);
  assert.match(source, /committedAssessmentId/);
  assert.match(source, /assessment_completed/);
  const assessmentBranch = source.slice(source.indexOf("const runAssessment"), source.indexOf("const recordDecision"));
  assert.doesNotMatch(assessmentBranch, /getLatestDashboard|location\.assign|sessionStorage/);
});
