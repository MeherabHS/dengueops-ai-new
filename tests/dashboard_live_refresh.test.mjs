import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";

const read=path=>readFile(new URL(`../${path}`,import.meta.url),"utf8");

test("dashboard uses one bounded read-only latest-authority poller",async()=>{
  const hook=await read("components/overview/useDashboardLiveRefresh.ts");
  assert.match(hook,/DASHBOARD_POLL_INTERVAL_MS = 2_500/);
  assert.match(hook,/DASHBOARD_POLL_TIMEOUT_MS = 120_000/);
  assert.match(hook,/\/api\/dashboard\/latest\?deployment=dhaka_south/);
  assert.match(hook,/method: "GET"/);
  assert.doesNotMatch(hook,/method: "POST"|enqueue|preparedness\/|monitoring\/summary/);
  assert.equal((hook.match(/setTimeout\(/g)??[]).length,1);
});

test("all pending evidence shares the same terminal-aware loop",async()=>{
  const hook=await read("components/overview/useDashboardLiveRefresh.ts");
  for(const signal of ["preparednessStatus","monitoringStatus","confidenceStatus"])assert.match(hook,new RegExp(`${signal} === \\"pending\\"`));
  assert.match(hook,/if \(vm === null \|\| !dashboardHasPendingEvidence\(vm\)\)/);
  assert.match(hook,/if \(!dashboardHasPendingEvidence\(latest.dashboard\)\) return/);
  assert.match(hook,/clearTimeout\(timer\)/);
  assert.match(hook,/controller\?\.abort\(\)/);
});

test("refresh replaces the full verified view and preserves it on transient errors",async()=>{
  const [hook,page]=await Promise.all([read("components/overview/useDashboardLiveRefresh.ts"),read("app/dashboard/page.tsx")]);
  assert.match(hook,/latest.dashboard.latestRun.runId === latest.runId/);
  assert.match(hook,/acceptVerified\(latest.dashboard\)/);
  assert.match(page,/setState\(\{status:"verified",vm:dashboard\}\)/);
  assert.doesNotMatch(hook,/location\.reload|router\.refresh/);
  assert.match(hook,/catch \(error\)/);
});

test("authentication loss, unmount, and timeout stop polling",async()=>{
  const hook=await read("components/overview/useDashboardLiveRefresh.ts");
  assert.match(hook,/response.status === 401 \|\| response.status === 403\) return/);
  assert.match(hook,/remaining <= 0/);
  assert.match(hook,/setTimedOutRunId\(runId\)/);
  assert.match(hook,/active = false/);
  assert.match(hook,/controller\?\.abort\(\)/);
});

test("server supplies explicit pending and terminal signals from verified authority",async()=>{
  const [reader,vm]=await Promise.all([read("lib/runtime/dashboard-reader.ts"),read("lib/dashboard-view-model.ts")]);
  assert.match(reader,/readVerifiedCurrentForecast/);
  assert.match(reader,/downstreamPending/);
  assert.match(reader,/preparednessStatus:operational\?"available":calculating\?"pending":"unavailable"/);
  assert.match(reader,/monitoringStatus:monitoring.availabilityStatus/);
  assert.match(reader,/confidenceStatus:monitoring.confidence.status/);
  assert.match(vm,/downstreamEvidence/);
});
