import assert from "node:assert/strict";
import { cp, mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";

const cwd = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));

function run(code, runtimeRoot = path.join(cwd, "runtime")) {
  return JSON.parse(execFileSync(process.execPath, [
    "--conditions=react-server",
    "--import=tsx",
    "--eval", code,
  ], {
    cwd,
    env: { ...process.env, DENGUEOPS_RUNTIME_ROOT: runtimeRoot },
    encoding: "utf8",
  }));
}

test("canonical public model uses current verified evidence and governed presentation semantics", () => {
  const value = run(`
    const m=await import('./lib/community/public-read-model.ts'); const api=m.default||m;
    const forecast=await api.readPublicForecast();
    const dashboards=[];
    for(const scenario of [null,'baseline_availability','constrained_availability','severe_constraint']) dashboards.push(await api.readPublicDashboard(scenario));
    console.log(JSON.stringify({forecast,dashboards,mappings:[
      api.mapReadinessStatus('calculated_synthetic_gap_present'),
      api.mapReadinessStatus('formula_not_configured'),
      api.mapReadinessStatus('no_calculated_synthetic_gap'),
      api.mapReadinessStatus('insufficient_capacity_reference')
    ]}));
  `);
  assert.equal(value.forecast.forecast.forecastedCases, 144);
  assert.deepEqual(value.forecast.forecast.latestObservedPoint, { period: "2024-W24", date: null, cases: 107 });
  assert.equal(value.forecast.forecast.forecast_growth_category, "increasing");
  assert.equal(value.forecast.forecast.directionLabel, "Expected rise");
  assert.equal(value.forecast.forecast.growthPercentage, null);
  assert.equal(value.forecast.forecast.uncertainty.intervalAvailable, false);
  assert.equal(value.forecast.forecast.recentObservedSeries.length, 52);
  assert.deepEqual(value.dashboards.map(d => d.preparedness.selectedScenario), [
    "severe_constraint", "baseline_availability", "constrained_availability", "severe_constraint",
  ]);
  for (const dashboard of value.dashboards) {
    assert.equal(dashboard.forecast.forecastedCases, 144);
    assert.equal(dashboard.preparedness.participatingHospitals, 13);
    assert.equal(dashboard.preparedness.capacityKnownHospitals, 9);
    assert.equal(dashboard.preparedness.capacityUnknownHospitals, 4);
    assert.equal(dashboard.preparedness.noCalculatedGapHospitals, 9);
    assert.equal(dashboard.preparedness.insufficientDataHospitals, 4);
    assert.equal(dashboard.preparedness.hospitals.some(h => h.readinessStatus === "critical"), false);
  }
  assert.deepEqual(value.mappings, ["warning", "not_calculated", "no_calculated_gap", "insufficient_data"]);
});

test("tampered forecast pointer and artifact fail closed without bundled fallback", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dengueops-community-"));
  const sourcePointer = path.join(cwd, "runtime", "deployments", "dhaka_south", "latest.json");
  const pointer = JSON.parse(await readFile(sourcePointer, "utf8"));
  const targetPointer = path.join(root, "deployments", "dhaka_south", "latest.json");
  await mkdir(path.dirname(targetPointer), { recursive: true });
  await writeFile(targetPointer, JSON.stringify({ ...pointer, dashboardSummarySha256: "0".repeat(64) }));
  assert.equal(run(`
    const m=await import('./lib/community/public-read-model.ts'); const api=m.default||m;
    try{await api.readPublicForecast();console.log(JSON.stringify({failed:false}));}
    catch(error){console.log(JSON.stringify({failed:true,code:error.code}));}
  `, root).failed, true);
  await writeFile(targetPointer, JSON.stringify(pointer));
  await cp(
    path.join(cwd, "runtime", "runs", pointer.runId),
    path.join(root, "runs", pointer.runId),
    { recursive: true },
  );
  await writeFile(path.join(root, "runs", pointer.runId, "artifacts", "forecast_output.json"), "{}");
  assert.equal(run(`
    const m=await import('./lib/community/public-read-model.ts'); const api=m.default||m;
    try{await api.readPublicForecast();console.log(JSON.stringify({failed:false}));}
    catch(error){console.log(JSON.stringify({failed:true,code:error.code}));}
  `, root).failed, true);
});

test("tampered current hospital inventory fails closed", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dengueops-inventory-"));
  await cp(
    path.join(cwd, "runtime", "deployments", "dhaka_south", "hospital-inventory"),
    path.join(root, "deployments", "dhaka_south", "hospital-inventory"),
    { recursive: true },
  );
  await cp(
    path.join(cwd, "runtime", "hospital-inventories", "dhaka-government-hospitals-20260729-v3"),
    path.join(root, "hospital-inventories", "dhaka-government-hospitals-20260729-v3"),
    { recursive: true },
  );
  const artifact = path.join(root, "hospital-inventories", "dhaka-government-hospitals-20260729-v3", "artifacts", "hospital_inventory.json");
  const inventory = JSON.parse(await readFile(artifact, "utf8"));
  inventory.hospitals[0].officialName = "Tampered";
  await writeFile(artifact, JSON.stringify(inventory));
  assert.equal(run(`
    const m=await import('./lib/runtime/hospital-inventory-reader.ts'); const api=m.default||m;
    try{await api.readVerifiedCurrentHospitalInventory(process.env.DENGUEOPS_RUNTIME_ROOT,'dhaka_south');console.log(JSON.stringify({failed:false}));}
    catch(error){console.log(JSON.stringify({failed:true,code:error.code}));}
  `, root).failed, true);
});
