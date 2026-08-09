import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const root = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));

function runFormatter(env) {
  return execFileSync(process.execPath, [
    "--conditions=react-server",
    "--import=tsx",
    "--eval",
    "const imported=await import('./lib/formatters.ts');const m=imported.default||imported;console.log(m.formatDhakaDateTime('2026-07-16T11:26:36.000Z'));console.log(m.formatDhakaDateTime('invalid'));",
  ], { cwd: root, env: { ...process.env, ...env }, encoding: "utf8" }).trim().split(/\r?\n/);
}

function runDashboardLabels() {
  return execFileSync(process.execPath, [
    "--conditions=react-server",
    "--import=tsx",
    "--eval",
    "const imported=await import('./lib/runtime/dashboard-reader.ts');const m=imported.default||imported;console.log(m.dashboardModelLabel('poisson_gam'));console.log(m.dashboardModelLabel('hist_gradient_boosting'));for(const value of ['SplinePoissonRegressor','unsupported_model',null]){try{m.dashboardModelLabel(value);console.log('unsafe')}catch{console.log('rejected')}}",
  ], { cwd: root, encoding: "utf8" }).trim().split(/\r?\n/);
}

test("dashboard timestamp formatting is deterministic across host locale and timezone", () => {
  const utc = runFormatter({ TZ: "UTC", LANG: "en_US.UTF-8" });
  const pacific = runFormatter({ TZ: "America/Los_Angeles", LANG: "fr_FR.UTF-8" });
  assert.deepEqual(utc, pacific);
  assert.equal(utc[0], "16 Jul 2026, 17:26:36 — Dhaka time");
  assert.equal(utc[1], "Not available");
});

test("dashboard projects a structured accepted period to display-ready text", async () => {
  const reader = await readFile(path.join(root, "lib/runtime/dashboard-reader.ts"), "utf8");
  const card = await readFile(path.join(root, "components/overview/LatestRunCard.tsx"), "utf8");
  assert.match(reader, /acceptedPeriodLabel\(validation\.acceptedPeriod\)/);
  assert.match(reader, /return `\$\{period\.start\} – \$\{period\.end\}`/);
  assert.match(reader, /exactKeys\(period, \["start", "end"\]\)/);
  assert.doesNotMatch(reader, /acceptedPeriod as OverviewViewModel/);
  assert.match(card, /\{run\.acceptedPeriod\}/);
  assert.doesNotMatch(card, /toLocaleString\(/);
});

test("active dashboard rendering uses the shared deterministic formatter", async () => {
  const page = await readFile(path.join(root, "app/dashboard/page.tsx"), "utf8");
  const card = await readFile(path.join(root, "components/overview/LatestRunCard.tsx"), "utf8");
  assert.match(page, /formatDhakaDateTime\(vm\.latestRun\.timestamp\)/);
  assert.match(card, /formatDhakaDateTime\(run\.timestamp\)/);
  assert.doesNotMatch(`${page}\n${card}`, /toLocaleString\(/);
  assert.doesNotMatch(`${page}\n${card}`, /suppressHydrationWarning/);
});

test("normal dashboard summary hides internal authority identifiers", async () => {
  const card = await readFile(path.join(root, "components/overview/LatestRunCard.tsx"), "utf8");
  assert.doesNotMatch(card, /run\.runId|Run ID|SHA-256|assignmentId|assessmentId/);
});

test("dashboard waits for exact current authority and never promotes cache or bundled evidence",async()=>{
  const page=await readFile(path.join(root,"app/dashboard/page.tsx"),"utf8");
  const reader=await readFile(path.join(root,"lib/runtime/dashboard-reader.ts"),"utf8");
  assert.match(page,/Verifying current forecast authority/);
  assert.match(page,/Current forecast authority unavailable/);
  assert.match(page,/latest\.dashboard\.latestRun\.runId===latest\.runId/);
  assert.doesNotMatch(page,/sessionStorage|dengueops-latest-dashboard|bundledOverviewViewModel/);
  assert.doesNotMatch(reader,/return \{ sourceType: "bundled_benchmark"/);
});

test("point-only forecasts hide the interval series and use truthful wording",async()=>{
  const page=await readFile(path.join(root,"app/dashboard/page.tsx"),"utf8");
  const chart=await readFile(path.join(root,"components/overview/ForecastTrendChart.tsx"),"utf8");
  const reader=await readFile(path.join(root,"lib/runtime/dashboard-reader.ts"),"utf8");
  assert.match(page,/Point forecast only/);
  assert.match(page,/Prediction interval unavailable/);
  assert.doesNotMatch(page,/Pending calibration/);
  assert.match(chart,/\{rangeAvailable\?<Scatter/);
  assert.match(chart,/name="Prediction interval"/);
  assert.doesNotMatch(chart,/name="Empirical range"/);
  assert.match(reader,/forecast\.uncertaintyStatus==="governed_available"/);
  assert.match(reader,/lower!==null&&upper!==null&&lower<=upper/);
  assert.match(reader,/lower: calibrated \? value\.forecast\.empiricalLower : null/);
});

test("dashboard model projection uses bounded candidate identity instead of artifact display labels", async () => {
  const labels = runDashboardLabels();
  assert.deepEqual(labels, [
    "Poisson GAM",
    "Histogram gradient boosting",
    "rejected",
    "rejected",
    "rejected",
  ]);
  const reader = await readFile(path.join(root, "lib/runtime/dashboard-reader.ts"), "utf8");
  assert.match(reader, /label: dashboardModelLabel\(model\.modelId\)/);
  assert.doesNotMatch(reader, /label: String\(model\.modelLabel\)/);
  assert.match(reader, /runId: String\(run\.runId\)/);
});
