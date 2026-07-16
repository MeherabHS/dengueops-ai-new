import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("Validation accepts only a UUID and separates uploaded from bundled evidence", async () => {
  const source = await read("app/validation/page.tsx");
  assert.match(source, /searchParams: Promise/);
  assert.match(source, /await searchParams/);
  assert.match(source, /UUID\.test/);
  assert.match(source, /Uploaded Dataset Assessment/);
  assert.match(source, /Bundled Benchmark Evidence/);
  assert.match(source, /RuntimeAssessmentWorkflow/);
  assert.match(source, /No runtime path was accessed/);
});

test("runtime assessment panel renders governed evidence and existing decision workflow", async () => {
  const source = await read("components/validation/RuntimeAssessmentWorkflow.tsx");
  assert.match(source, /getDatasetAssessment/);
  assert.match(source, /ModelSuitabilitySummary/);
  assert.match(source, /ApprovalPanel/);
  assert.match(source, /recordAssessmentDecision/);
  assert.match(source, /startApprovedForecast/);
  assert.match(source, /getLatestDashboard/);
  assert.match(source, /separate from the bundled benchmark, empirical-range calibration, outcome monitoring, and preparedness evidence/);
  assert.doesNotMatch(source, /MAPE|R²|operatorIdentifier|internalDecisionSecret|x-dengueops-internal-decision-secret/);
});

test("leaderboard uses backend rank, shows all evidence, and does not add ungoverned metrics", async () => {
  const source = await read("components/forecast/ModelLeaderboard.tsx");
  assert.match(source, /assessment\.workflow\.candidates/);
  assert.match(source, /displayRank/);
  assert.match(source, /modelFamily/);
  assert.match(source, /candidate\.reasons\.map/);
  assert.match(source, /Technical winner/);
  assert.match(source, /Current deployment model/);
  assert.match(source, /Evaluation only/);
  assert.doesNotMatch(source, /\.sort\(\(a, b\).*mae|MAPE|R²/);
});
