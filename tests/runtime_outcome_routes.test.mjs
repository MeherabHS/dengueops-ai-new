import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("outcome submission is protected, strict, and worker-only", async () => {
  const source=await read("app/api/runtime/forecast-outcomes/route.ts");
  assert.match(source,/DENGUEOPS_INTERNAL_MONITORING|internalMonitoringEnabled/);
  assert.match(source,/x-dengueops-internal-monitoring-secret/);
  assert.match(source,/timingSafeEqual/);
  assert.match(source,/unsupported or missing fields/);
  assert.match(source,/createPendingJob/);
  assert.match(source,/schemaVersion:"2\.0"/);
  assert.match(source,/policy\.schema_version!=="2\.0"/);
  assert.match(source,/status:202/);
  assert.doesNotMatch(source,/evaluate_outcome|signedError|absoluteError/);
  assert.match(source,/Response\.json\(\{ok:true,outcomeId,jobId,status:"queued",statusUrl/);
});

test("verified outcome and monitoring reads are no-cache and redact audit identity", async () => {
  const outcome=await read("app/api/runtime/forecast-outcomes/[outcomeId]/route.ts");
  const summary=await read("app/api/runtime/monitoring/summary/route.ts");
  const store=await read("lib/runtime/outcome-store.ts");
  assert.match(outcome,/readVerifiedForecastOutcome/);assert.match(outcome,/no-store/);
  assert.match(summary,/readVerifiedMonitoringSummary/);assert.match(summary,/no-store/);
  assert.match(store,/outcomeCommitSha256/);assert.match(store,/monitoringSummarySha256/);
  assert.match(store,/outcomeSetSha256/);assert.match(store,/approved_forecast_p2/);
  assert.doesNotMatch(store,/operatorIdentifier\s*:/);
});

test("outcome paths use separate monitoring pointer", async()=>{
  const paths=await read("lib/runtime/paths.ts");const commit=await read("analytics/runtime_forecast_outcome_commit.py");
  assert.match(paths,/forecast-outcomes/);assert.match(paths,/monitoring.*latest\.json/s);
  assert.match(commit,/latestForecastPointerModified/);assert.doesNotMatch(commit,/atomic_json\(latest_path/);
});
