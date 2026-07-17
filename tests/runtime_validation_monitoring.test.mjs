import test from "node:test";
import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
const read=path=>readFile(new URL(`../${path}`,import.meta.url),"utf8");

test("Validation page exposes read-only lifecycle-aware monitoring",async()=>{
  const page=await read("app/validation/page.tsx"),panel=await read("components/validation/ForecastOutcomeMonitoringSummary.tsx"),client=await read("lib/runtime/client.ts");
  assert.match(page,/ForecastOutcomeMonitoringSummary/);
  assert.match(panel,/quick_forecast_p1/);assert.match(panel,/approved_forecast_p1/);assert.match(panel,/approved_forecast_p2/);
  assert.match(panel,/does not classify degradation/);assert.match(panel,/Missing actuals are pending evidence/);assert.match(panel,/Unknown source rejected/);
  assert.match(client,/\/api\/runtime\/monitoring\/summary/);
  assert.doesNotMatch(panel+client,/x-dengueops-internal-monitoring-secret|DENGUEOPS_INTERNAL_MONITORING_SECRET/);
  assert.doesNotMatch(panel,/fetch\([^)]*forecast-outcomes|method:\s*["']POST/);
});
