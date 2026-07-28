import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { cp, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const cwd = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));

test("current and explicit availability packages verify against one current forecast", () => {
  const output = execFileSync(process.execPath, [
    "--conditions=react-server",
    "--import=tsx",
    "--eval",
    `const dm=await import('./lib/runtime/dashboard-reader.ts');const im=await import('./lib/runtime/hospital-inventory-reader.ts');const pm=await import('./lib/runtime/preparedness-reader.ts');
     const d=dm.default||dm,i=im.default||im,p=pm.default||pm,root=process.env.DENGUEOPS_RUNTIME_ROOT;
     const f=await d.readVerifiedCurrentForecast(root,'dhaka_south'),inv=await i.readVerifiedCurrentHospitalInventory(root,'dhaka_south');
     const rows=[];for(const s of [null,'baseline_availability','constrained_availability','severe_constraint']){const q=await p.readVerifiedPreparedness(root,s,f,inv);rows.push({scenario:q.evidence.scenarioId,run:q.evidence.forecastSource.runId,count:q.evidence.hospitals.length,sha:q.evidenceSha256});}
     console.log(JSON.stringify({run:f.pointer.runId,rows}));`,
  ], {
    cwd,
    env: { ...process.env, DENGUEOPS_RUNTIME_ROOT: path.join(cwd, "runtime") },
    encoding: "utf8",
  });
  const value = JSON.parse(output);
  assert.equal(value.run, "8845b4f8-1661-4d84-a26d-e4ccc25e4416");
  assert.deepEqual(value.rows.map(row => row.scenario), [
    "severe_constraint", "baseline_availability", "constrained_availability", "severe_constraint",
  ]);
  assert.equal(new Set(value.rows.map(row => row.run)).size, 1);
  assert.equal(value.rows.every(row => row.count === 13 && /^[a-f0-9]{64}$/.test(row.sha)), true);
});

test("preparedness reader verifies immutable hashes without evaluating formulas", async () => {
  const source = await import("node:fs/promises").then(fs =>
    fs.readFile(path.join(cwd, "lib", "runtime", "preparedness-reader.ts"), "utf8"));
  assert.match(source, /artifact hash/);
  assert.match(source, /forecastCommitSha256/);
  assert.match(source, /official_hospital_inventory_snapshot\.json/);
  assert.doesNotMatch(source, /\beval\s*\(|safeFormula|evaluateFormula/);
});

test("tampered current preparedness evidence fails closed", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dengueops-preparedness-"));
  const runId = "8845b4f8-1661-4d84-a26d-e4ccc25e4416";
  const inventoryId = "dhaka-government-hospitals-20260729-v3";
  const preparednessId = "2e3bcb1e-e4c5-4601-b588-476459d1896e";
  for (const [source, target] of [
    [`runtime/runs/${runId}`, `runs/${runId}`],
    ["runtime/deployments/dhaka_south/latest.json", "deployments/dhaka_south/latest.json"],
    ["runtime/deployments/dhaka_south/hospital-inventory", "deployments/dhaka_south/hospital-inventory"],
    [`runtime/hospital-inventories/${inventoryId}`, `hospital-inventories/${inventoryId}`],
    ["runtime/deployments/dhaka_south/hospital-preparedness-qualification", "deployments/dhaka_south/hospital-preparedness-qualification"],
    [`runtime/hospital-preparedness-qualification/${preparednessId}`, `hospital-preparedness-qualification/${preparednessId}`],
  ]) {
    await cp(path.join(cwd, source), path.join(root, target), { recursive: true });
  }
  const evidencePath = path.join(root, "hospital-preparedness-qualification", preparednessId, "artifacts", "preparedness_evidence.json");
  const evidence = JSON.parse(await readFile(evidencePath, "utf8"));
  evidence.hospitals[0].syntheticGap = "1";
  await writeFile(evidencePath, JSON.stringify(evidence));
  const output = execFileSync(process.execPath, [
    "--conditions=react-server", "--import=tsx", "--eval",
    `const dm=await import('./lib/runtime/dashboard-reader.ts');const im=await import('./lib/runtime/hospital-inventory-reader.ts');const pm=await import('./lib/runtime/preparedness-reader.ts');
     const d=dm.default||dm,i=im.default||im,p=pm.default||pm,root=process.env.DENGUEOPS_RUNTIME_ROOT;
     try{const f=await d.readVerifiedCurrentForecast(root,'dhaka_south'),inv=await i.readVerifiedCurrentHospitalInventory(root,'dhaka_south');await p.readVerifiedPreparedness(root,null,f,inv);console.log(JSON.stringify({failed:false}));}
     catch(error){console.log(JSON.stringify({failed:true,code:error.code}));}`,
  ], { cwd, env: { ...process.env, DENGUEOPS_RUNTIME_ROOT: root }, encoding: "utf8" });
  assert.equal(JSON.parse(output).failed, true);
});
