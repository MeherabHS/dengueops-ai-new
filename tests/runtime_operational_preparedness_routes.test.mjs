import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

const read=path=>readFile(new URL(`../${path}`,import.meta.url),"utf8");

test("preparedness mutation accepts intent only and resolves every authority server-side",async()=>{
  const route=await read("app/api/runtime/preparedness/route.ts");
  assert.match(route,/requireSuperUserMutation/);
  assert.match(route,/Object\.keys\(body\)\.length!==0/);
  assert.match(route,/resolveCurrentPreparednessAuthority/);
  assert.match(route,/authoritySnapshotSha256/);
  assert.doesNotMatch(route,/body\.(?:formula|formulaId|formulaSha|forecastRunId|modelId|inventoryId)/);
});

test("forecast handoff is nonblocking and preparedness start is idempotently recoverable",async()=>{
  const panel=await read("components/forecast/QuickForecastRunPanel.tsx");
  const route=await read("app/api/runtime/preparedness/route.ts");
  const worker=await read("analytics/runtime_worker.py");
  assert.match(panel,/void startOperationalPreparedness\(\)/);
  assert.match(panel,/preparedness\.ok/);
  assert.match(panel,/Preparedness could not be started/);
  assert.match(worker,/enqueue_operational_preparedness_job/);
  assert.match(worker,/kind in \{"quick_forecast", "approved_forecast"\}/);
  assert.match(route,/operationalPreparednessPaths/);
  assert.match(route,/existingJob/);
  assert.match(route,/recovered:true/);
});

test("dashboard and Community consume verified operational evidence without qualification fallback",async()=>{
  const dashboard=await read("lib/runtime/dashboard-reader.ts");
  const community=await read("lib/community/public-read-model.ts");
  const table=await read("components/overview/OperationalPreparednessTable.tsx");
  assert.match(dashboard,/readCurrentOperationalPreparedness/);
  assert.match(dashboard,/overviewFromVerified\(verified,operational,reason,monitoring,calculating\)/);
  assert.doesNotMatch(dashboard,/calculating\|\|downstreamPending/);
  assert.match(community,/mapOperationalPreparedness/);
  assert.match(community,/qualificationPreparedness/);
  assert.match(table,/Current live availability/);
  assert.match(table,/Not reported/);
  assert.match(table,/required operational input missing/);
  assert.doesNotMatch(table,/syntheticAvailableBedUnits|availableResource/);
});
