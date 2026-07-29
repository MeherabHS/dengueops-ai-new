import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("decision route is authenticated and enforces exact governed p2-v3 payloads", async () => {
  const source = await read("app/api/runtime/assessments/[assessmentId]/decisions/route.ts");
  assert.match(source, /authorizeSuperUserOrService/);
  assert.match(source, /approve_technical_winner/);
  assert.match(source, /approve_eligible_non_winner/);
  assert.match(source, /technicalWinnerNotSelectedAcknowledged/);
  assert.match(source, /uncertaintyLimitationsAcknowledged/);
  assert.match(source, /expectedKeys/);
});

test("approved forecast start accepts only a decision commit and reserves authorization", async () => {
  const source = await read("app/api/runtime/decisions/[decisionId]/forecast/route.ts");
  assert.match(source, /Object\.keys\(body\).*expectedDecisionCommitSha256/s);
  assert.match(source, /reservation/);
  assert.match(source, /approved_forecast/);
  assert.doesNotMatch(source, /modelId:\s*body|parameters:\s*body/);
});

test("authorization remains one-run, expiry checked, and never released by failed execution", async () => {
  const route = await read("app/api/runtime/decisions/[decisionId]/forecast/route.ts");
  const store = await read("lib/runtime/decision-store.ts");
  assert.match(route, /forecast_authorization_expired/);
  assert.match(route, /auth\.reservation/);
  assert.match(route, /already being reserved/);
  assert.doesNotMatch(route, /releaseAuthorization|automaticRetry/i);
  assert.match(store, /authorizationCommitSha256/);
});

test("approved forecast UI verifies commit evidence and remains on the workflow", async () => {
  const panel = await read("components/forecast/ApprovedForecastPanel.tsx");
  const workflow = await read("components/forecast/ForecastRunWorkflow.tsx");
  assert.match(panel, /approvedForecastCommitSha256/);
  assert.match(panel, /job\.committedRunId !== base\.runId/);
  assert.match(panel, /Ready for governed assignment/);
  assert.doesNotMatch([panel, workflow].join("\n"), /location\.assign|\/dashboard/);
});

test("protected decision secret is confined to server routes", async () => {
  for (const file of ["components/forecast/ForecastRunWorkflow.tsx", "components/forecast/ApprovedForecastPanel.tsx", "lib/runtime/client.ts"]) {
    const source = await read(file);
    assert.doesNotMatch(source, /x-dengueops-internal-decision-secret|internalDecisionSecret/);
  }
});
