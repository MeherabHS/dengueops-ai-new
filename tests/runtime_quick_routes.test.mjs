import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("quick start accepts identities only and never executes Python in request", async () => {
  const source = await read("app/api/runtime/runs/quick/route.ts");
  assert.match(source, /workspaceId.*datasetId.*deploymentId.*validationRecordSha256/s);
  assert.match(source, /unexpected_quick_forecast_field/);
  assert.doesNotMatch(source, /spawn\(|exec\(|modelId\s*:/);
});

test("frontend refresh is gated on completed committed run identity", async () => {
  const source = await read("components/forecast/ForecastRunWorkflow.tsx");
  assert.match(source, /job\.status === "completed"/);
  assert.match(source, /latest\.runId !== job\.committedRunId/);
  assert.match(source, /dengueops-latest-dashboard/);
  assert.match(source, /location\.assign\("\/dashboard"\)/);
  assert.doesNotMatch(source, /EventSource|WebSocket/);
});

test("uploaded dashboard uses explicit unavailable states", async () => {
  const source = await read("lib/runtime/dashboard-reader.ts");
  assert.match(source, /availabilityStatus: value\.forecast\.uncertaintyStatus/);
  assert.match(source, /lower: calibrated \? value\.forecast\.empiricalLower : null/);
  assert.match(source, /historicalCoverage: calibrated \? value\.forecast\.historicalCoverage : null/);
  assert.match(source, /availabilityStatus: value\.preparedness\.availabilityStatus/);
  assert.doesNotMatch(source, /53\s*[–-]\s*187|87\s*\/\s*120\s*\/\s*153/);
});
