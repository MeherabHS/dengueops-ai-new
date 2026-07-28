import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const cwd = path.resolve(new URL("..", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
const forbidden = new Set([
  "candidate", "model", "modelFamily", "technicalWinner", "assessmentId", "decisionId",
  "assignmentId", "runId", "policyVersion", "policySha", "artifactSha", "commitSha",
  "pointerSha", "trainingRows", "featureCount", "fitCount", "calibrationInternals",
  "expertOverride", "modelAuthorityMutation", "allocationShare", "formulaId",
  "formulaExpression", "coefficient", "sourcePath",
]);

function assertPublicKeys(value) {
  if (Array.isArray(value)) return value.forEach(assertPublicKeys);
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    assert.equal(forbidden.has(key), false, `forbidden public key: ${key}`);
    assertPublicKeys(child);
  }
}

test("community routes return curated no-store responses and reject unsupported scenarios", async () => {
  const pointers = [
    "runtime/deployments/dhaka_south/latest.json",
    "runtime/deployments/dhaka_south/hospital-inventory/latest.json",
    "runtime/deployments/dhaka_south/hospital-preparedness-qualification/latest.json",
  ];
  const before = await Promise.all(pointers.map(file => readFile(path.join(cwd, file), "utf8")));
  const output = execFileSync(process.execPath, [
    "--conditions=react-server",
    "--import=tsx",
    "--eval",
    `const fm=await import('./app/api/community/forecast/current/route.ts'),hm=await import('./app/api/community/hospitals/route.ts'),dm=await import('./app/api/community/dashboard/route.ts');
     const f=fm.default||fm,h=hm.default||hm,d=dm.default||dm;
     const responses=[];
     for(const [name,promise] of [
       ['forecast',f.GET()],
       ['hospitals',h.GET(new Request('http://localhost/api/community/hospitals'))],
       ['baseline',h.GET(new Request('http://localhost/api/community/hospitals?scenario=baseline_availability'))],
       ['dashboard',d.GET(new Request('http://localhost/api/community/dashboard'))],
       ['invalid',d.GET(new Request('http://localhost/api/community/dashboard?scenario=unsupported'))],
     ]){const r=await promise;responses.push({name,status:r.status,cache:r.headers.get('cache-control'),body:await r.json()});}
     console.log(JSON.stringify(responses));`,
  ], {
    cwd,
    env: { ...process.env, DENGUEOPS_RUNTIME_ROOT: path.join(cwd, "runtime") },
    encoding: "utf8",
  });
  const responses = JSON.parse(output);
  for (const response of responses) {
    assert.equal(response.cache, "no-store");
    assertPublicKeys(response.body);
  }
  assert.deepEqual(responses.map(item => item.status), [200, 200, 200, 200, 400]);
  assert.equal(responses[0].body.forecast.forecastedCases, 144);
  assert.equal(responses[1].body.preparedness.participatingHospitals, 13);
  assert.equal(responses[2].body.preparedness.selectedScenario, "baseline_availability");
  assert.equal(responses[3].body.preparedness.selectedScenario, "severe_constraint");
  assert.equal(JSON.stringify(responses).includes("\\\\"), false);
  const after = await Promise.all(pointers.map(file => readFile(path.join(cwd, file), "utf8")));
  assert.deepEqual(after, before);
});

test("community route source is GET-only and contains no write or fallback authority", async () => {
  const fs = await import("node:fs/promises");
  const files = [
    "app/api/community/forecast/current/route.ts",
    "app/api/community/hospitals/route.ts",
    "app/api/community/dashboard/route.ts",
    "lib/community/public-read-model.ts",
  ];
  const source = (await Promise.all(files.map(file => fs.readFile(path.join(cwd, file), "utf8")))).join("\n");
  assert.doesNotMatch(source, /export async function (?:POST|PUT|PATCH|DELETE)/);
  assert.doesNotMatch(source, /data\/dashboard_summary|data\/forecast_output|directives\.json|demo-data|sessionStorage|bundledOverviewViewModel/);
  assert.doesNotMatch(source, /writeFile|rename\(|mkdir\(|enqueue|spawn\(/);
});
