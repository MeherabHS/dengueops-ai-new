import assert from "node:assert/strict";
import { cp, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import test from "node:test";
import { copyRuntimeWithCurrentQualifications } from "./current_qualification_fixture.mjs";

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

async function operationalRuntime() {
  const root = await copyRuntimeWithCurrentQualifications(cwd, "dengueops-community-operational-");
  const code = `import json,sys,uuid\nfrom datetime import datetime,timezone\nfrom pathlib import Path\nsys.path.insert(0,'analytics')\nfrom runtime_operational_preparedness import resolve_authorities,build_artifacts,write_staging\nfrom runtime_operational_preparedness_commit import commit_staging\nr=Path(sys.argv[1]);a=resolve_authorities(r);pid=str(uuid.uuid4());jid=str(uuid.uuid4());st=r/'operational-preparedness-staging'/pid;summary,facilities=build_artifacts(a,pid,datetime.now(timezone.utc).isoformat().replace('+00:00','Z'));write_staging(st,summary,facilities);commit_staging(r,st,{'preparednessId':pid,'jobId':jid,'deploymentId':'dhaka_south','authoritySnapshotSha256':a['authoritySnapshotSha256']},a)`;
  const executable = process.platform === "win32" ? "py" : (process.env.DENGUEOPS_PYTHON_EXECUTABLE || "python");
  const args = process.platform === "win32" ? ["-3.13", "-c", code, root] : ["-c", code, root];
  execFileSync(executable, args, { cwd, env: { ...process.env, DENGUEOPS_RUNTIME_ROOT: root }, encoding: "utf8" });
  return root;
}

test("canonical public model prefers current operational preparedness and separates qualification", async t => {
  const runtimeRoot = await operationalRuntime();
  t.after(()=>rm(runtimeRoot,{recursive:true,force:true}));
  const value = run(`
    const m=await import('./lib/community/public-read-model.ts'); const api=m.default||m;
    const d=await import('./lib/runtime/dashboard-reader.ts'); const dashboardApi=d.default||d;
    const forecast=await api.readPublicForecast();
    const dashboards=[];
    for(const scenario of [null,'baseline_availability','constrained_availability','severe_constraint']) dashboards.push(await api.readPublicDashboard(scenario));
    const web=await dashboardApi.readLatestDashboard('dhaka_south');
    console.log(JSON.stringify({forecast,dashboards,web,mappings:[
      api.mapReadinessStatus('calculated_synthetic_gap_present'),
      api.mapReadinessStatus('formula_not_configured'),
      api.mapReadinessStatus('no_calculated_synthetic_gap'),
      api.mapReadinessStatus('insufficient_capacity_reference')
    ]}));
  `, runtimeRoot);
  assert.equal(value.forecast.forecast.forecastedCases, value.web.dashboard.forecastCases);
  assert.equal(value.forecast.forecast.latestObservedPoint.cases, value.web.dashboard.latestObservedCases);
  assert.equal(value.forecast.forecast.latestObservedPoint.period, value.web.dashboard.history.at(-1).period);
  assert.equal(value.forecast.forecast.forecast_growth_category, "increasing");
  assert.equal(value.forecast.forecast.directionLabel, "Expected rise");
  assert.equal(value.forecast.forecast.growthPercentage, null);
  assert.equal(value.forecast.forecast.uncertainty.intervalAvailable, value.web.dashboard.empiricalRange.isPredictionInterval);
  assert.equal(value.forecast.forecast.uncertainty.lower, value.web.dashboard.empiricalRange.lower);
  assert.equal(value.forecast.forecast.uncertainty.upper, value.web.dashboard.empiricalRange.upper);
  assert.equal(value.forecast.forecast.uncertainty.publicLabel, "Calibrated prediction interval");
  assert.match(value.forecast.forecast.uncertainty.reason, /available for this exact committed forecast/);
  assert.equal(value.forecast.forecast.recentObservedSeries.length, 52);
  assert.equal(value.web.dashboard.preparedness.availabilityStatus,"available");
  assert.equal(value.web.dashboard.preparedness.rows.length,13);
  assert.deepEqual(value.dashboards.map(d => d.preparedness.selectedScenario), [null,null,null,null]);
  assert.deepEqual(value.dashboards.map(d => d.qualificationPreparedness?.selectedScenario ?? null), [null,"baseline_availability","constrained_availability","severe_constraint"]);
  for (const dashboard of value.dashboards) {
    assert.equal(dashboard.forecast.forecastedCases, value.web.dashboard.forecastCases);
    assert.equal(dashboard.preparedness.participatingHospitals, 13);
    assert.equal(dashboard.preparedness.capacityKnownHospitals, 9);
    assert.equal(dashboard.preparedness.capacityUnknownHospitals, 4);
    assert.equal(dashboard.preparedness.noCalculatedGapHospitals, 9);
    assert.equal(dashboard.preparedness.insufficientDataHospitals, 4);
    assert.equal(dashboard.preparedness.hospitals.some(h => h.readinessStatus === "critical"), false);
    assert.equal(dashboard.preparedness.evidenceClassification, "current_operational_preparedness");
    assert.equal(dashboard.preparedness.hospitals.every(h => h.currentAvailableBeds === null && h.syntheticAvailableBedUnits === null), true);
    assert.equal(dashboard.evidence.productionFormulaActivated, true);
    assert.equal(dashboard.evidence.operationalPreparednessEvidencePublished, true);
  }
  assert.deepEqual(value.mappings, ["warning", "not_calculated", "no_calculated_gap", "insufficient_data"]);
});

test("tampered forecast pointer and artifact fail closed without bundled fallback", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dengueops-community-"));
  t.after(()=>rm(root,{recursive:true,force:true}));
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

test("tampered current hospital inventory fails closed", async t => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dengueops-inventory-"));
  t.after(()=>rm(root,{recursive:true,force:true}));
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
