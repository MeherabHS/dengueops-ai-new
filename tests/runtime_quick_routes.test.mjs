import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, readFile, readdir, rm, unlink, writeFile } from "node:fs/promises";
import Module from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { require as tsxRequire } from "tsx/cjs/api";
import { findPython, spawnPythonSync } from "./node_python_runner.mjs";

const sessionSecret = "quick-route-test-session-secret-value-1234567890";
process.env.DENGUEOPS_SESSION_SECRET = sessionSecret;
const originalModuleLoad = Module._load;
Module._load = function loadForServerRouteTest(request, parent, isMain) {
  if (request === "server-only") {
    return {};
  }
  return originalModuleLoad.call(this, request, parent, isMain);
};
const [
  quickRouteImported,
  jobRouteImported,
  validateRouteImported,
  sessionImported,
] = [
  tsxRequire("../app/api/runtime/runs/quick/route.ts", import.meta.url),
  tsxRequire("../app/api/runtime/jobs/[jobId]/route.ts", import.meta.url),
  tsxRequire("../app/api/runtime/validate/route.ts", import.meta.url),
  tsxRequire("../lib/auth/session.ts", import.meta.url),
];
Module._load = originalModuleLoad;
const quickRouteModule = quickRouteImported.default ?? quickRouteImported;
const jobRouteModule = jobRouteImported.default ?? jobRouteImported;
const validateRouteModule = validateRouteImported.default ?? validateRouteImported;
const sessionModule = sessionImported.default ?? sessionImported;
const { createSessionToken, sessionCookieName } = sessionModule;
const sessionToken = await createSessionToken("quick-route-test-super-user");
const { POST: queueQuickForecast } = quickRouteModule;
const { GET: getRuntimeJob } = jobRouteModule;
const { POST: validateRuntime } = validateRouteModule;
let pythonAvailable = true;
try {
  findPython();
} catch {
  pythonAvailable = false;
}
function createFixture(base, modelId) {
  const built = spawnPythonSync(
    ["-m", "tests.runtime_active_model_parity_probe", "create-quick", base, modelId],
    { timeout: 360_000 },
  );
  assert.equal(built.status, 0, built.stdout + built.stderr);
  return JSON.parse(built.stdout.trim().split(/\r?\n/).at(-1));
}

function requestFor(fixture, extra = {}, authority = "super_user", omitExpectedPointer = false) {
  const headers = {
    "content-type": "application/json",
    ...(authority === "anonymous" ? {} : {
      cookie: `${sessionCookieName()}=${sessionToken}`,
      origin: authority === "cross_origin" ? "https://attacker.invalid" : "http://localhost",
      host: "localhost",
    }),
  };
  return new Request("http://localhost/api/runtime/runs/quick", {
    method: "POST",
    headers,
    body: JSON.stringify({
      workspaceId: fixture.workspaceId,
      datasetId: fixture.datasetId,
      deploymentId: "dhaka_south",
      validationRecordSha256: fixture.validationRecordSha256,
      ...(!omitExpectedPointer ? {
        expectedAssignmentPointerSha256: fixture.authority?.authoritySnapshotSha256
          ?? fixture.expectedAssignmentPointerSha256
          ?? "1".repeat(64),
      } : {}),
      ...extra,
    }),
  });
}

async function withRuntime(runtime, callback) {
  const previousRoot = process.env.DENGUEOPS_RUNTIME_ROOT;
  const previousPython = process.env.DENGUEOPS_PYTHON_EXECUTABLE;
  process.env.DENGUEOPS_RUNTIME_ROOT = runtime;
  if (pythonAvailable) process.env.DENGUEOPS_PYTHON_EXECUTABLE = findPython().command;
  try {
    return await callback();
  } finally {
    if (previousRoot === undefined) delete process.env.DENGUEOPS_RUNTIME_ROOT;
    else process.env.DENGUEOPS_RUNTIME_ROOT = previousRoot;
    if (previousPython === undefined) delete process.env.DENGUEOPS_PYTHON_EXECUTABLE;
    else process.env.DENGUEOPS_PYTHON_EXECUTABLE = previousPython;
  }
}

for (const modelId of ["random_forest", "ridge_regression"]) {
  test(`current ${modelId} assignment queues once and recovers the same exclusive start`, { timeout: 420_000, skip: !pythonAvailable }, async () => {
    const temporary = await mkdtemp(path.join(tmpdir(), `b6-quick-${modelId}-`));
    try {
      const fixture = createFixture(path.join(temporary, "fixture"), modelId);
      await withRuntime(fixture.runtime, async () => {
        if (modelId === "random_forest") {
          const form = new FormData();
          form.append("deploymentId", "dhaka_south");
          form.append("workflowMode", "quick_forecast");
          form.append("dengueFile", new Blob([await readFile(path.join(process.cwd(), "data", "dengue_cases.csv"))], { type: "text/csv" }), "dengue_cases.csv");
          form.append("climateFile", new Blob([await readFile(path.join(process.cwd(), "data", "climate_data.csv"))], { type: "text/csv" }), "climate_data.csv");
          const validationResponse = await validateRuntime(new Request("http://localhost/api/runtime/validate", {
            method: "POST",
            headers: {
              cookie: `${sessionCookieName()}=${sessionToken}`,
              origin: "http://localhost",
              host: "localhost",
            },
            body: form,
          }));
          assert.equal(validationResponse.status, 200, await validationResponse.clone().text());
          assert.deepEqual((await validationResponse.json()).activeModelAuthority, fixture.authority);
        }
        const response = await queueQuickForecast(requestFor(fixture));
        assert.equal(response.status, 202, await response.clone().text());
        const queued = await response.json();
        assert.equal(queued.recovered, false);
        assert.equal(queued.deploymentId, "dhaka_south");
        assert.deepEqual(queued.activeModelAuthority, fixture.authority);

        const jobPath = path.join(fixture.runtime, "jobs", "pending", `${queued.jobId}.json`);
        const job = JSON.parse(await readFile(jobPath, "utf8"));
        assert.equal(job.schemaVersion, "2.1");
        assert.equal(job.assignmentCommitSha256, fixture.authority.assignmentCommitSha256);
        assert.equal(job.lifecyclePolicySha256, fixture.authority.lifecyclePolicySha256);
        assert.equal(job.authoritySnapshotSha256, fixture.authority.authoritySnapshotSha256);
        assert.equal(job.resolvedPreprocessingIdentity, fixture.authority.preprocessingIdentity);
        assert.equal(job.quickPolicyVersion, "p2-v2");
        assert.equal(job.quickPolicySha256, "09c338d56737ba35b5a0db82c97a7e26222297dfbb07cba36bf0e5f831b9adc2");
        const markerPath = path.join(fixture.runtime, "workspaces", fixture.workspaceId, "metadata", "quick_forecast_started.json");
        const marker = JSON.parse(await readFile(markerPath, "utf8"));
        assert.equal(marker.schemaVersion, "2.0");
        assert.equal(marker.workflowType, "quick_forecast");
        assert.equal(marker.expectedAssignmentPointerSha256, fixture.authority.authoritySnapshotSha256);

        const recoveredResponse = await queueQuickForecast(requestFor(fixture));
        assert.equal(recoveredResponse.status, 200);
        const recovered = await recoveredResponse.json();
        assert.equal(recovered.recovered, true);
        assert.equal(recovered.jobId, queued.jobId);
        assert.equal(recovered.runId, queued.runId);
        assert.equal(recovered.statusUrl, queued.statusUrl);
        assert.equal((await readdir(path.join(fixture.runtime, "jobs", "pending"))).length, 1);

        const status = await getRuntimeJob(
          new Request(`http://localhost/api/runtime/jobs/${queued.jobId}`),
          { params: Promise.resolve({ jobId: queued.jobId }) },
        );
        assert.equal(status.status, 200);
        const statusValue = await status.json();
        assert.deepEqual(statusValue.activeModelAuthority, fixture.authority);
      });
    } finally {
      await rm(temporary, { recursive: true, force: true });
    }
  });
}

test("missing current assignment rejects without historical profile fallback", { timeout: 420_000, skip: !pythonAvailable }, async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "b6-quick-missing-"));
  try {
    const fixture = createFixture(path.join(temporary, "fixture"), "ridge_regression");
    await unlink(path.join(fixture.runtime, "deployments", "dhaka_south", "model-assignment", "latest.json"));
    await withRuntime(fixture.runtime, async () => {
      const response = await queueQuickForecast(requestFor(fixture));
      assert.equal(response.status, 404);
      assert.equal((await response.json()).error.code, "active_model_not_assigned");
    });
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test("tampered current assignment rejects before queue publication", { timeout: 420_000, skip: !pythonAvailable }, async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "b6-quick-tampered-"));
  try {
    const fixture = createFixture(path.join(temporary, "fixture"), "ridge_regression");
    const pointerPath = path.join(fixture.runtime, "deployments", "dhaka_south", "model-assignment", "latest.json");
    const pointer = JSON.parse(await readFile(pointerPath, "utf8"));
    pointer.assignmentCommitSha256 = "0".repeat(64);
    await writeFile(pointerPath, JSON.stringify(pointer));
    await withRuntime(fixture.runtime, async () => {
      const response = await queueQuickForecast(requestFor(fixture));
      assert.equal(response.status, 409);
      assert.equal((await response.json()).error.code, "active_model_integrity_error");
    });
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test("client-supplied model and authority overrides are rejected", async () => {
  const fixture = {
    workspaceId: "00000000-0000-4000-8000-000000000000",
    datasetId: "0".repeat(64),
    validationRecordSha256: "0".repeat(64),
  };
  for (const extra of [
    { modelId: "random_forest" },
    { candidateId: "random_forest" },
    { assignmentId: "00000000-0000-4000-8000-000000000000" },
    { lifecyclePolicySha256: "0".repeat(64) },
  ]) {
    const response = await queueQuickForecast(requestFor(fixture, extra));
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, "unexpected_quick_forecast_field");
  }
});

test("expected assignment pointer is required and must be a SHA-256 identity", async () => {
  const fixture = {
    workspaceId: "00000000-0000-4000-8000-000000000000",
    datasetId: "0".repeat(64),
    validationRecordSha256: "0".repeat(64),
  };
  const missing = await queueQuickForecast(requestFor(fixture, {}, "super_user", true));
  assert.equal(missing.status, 400);
  assert.equal((await missing.json()).error.code, "invalid_quick_forecast_request");
  const invalid = await queueQuickForecast(requestFor(fixture, { expectedAssignmentPointerSha256: "not-a-sha" }));
  assert.equal(invalid.status, 400);
  assert.equal((await invalid.json()).error.code, "invalid_quick_forecast_request");
});

test("stale assignment pointer rejects with 409 before enqueue", { timeout: 420_000, skip: !pythonAvailable }, async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "b9-quick-conflict-"));
  try {
    const fixture = createFixture(path.join(temporary, "fixture"), "ridge_regression");
    await withRuntime(fixture.runtime, async () => {
      const response = await queueQuickForecast(requestFor(fixture, { expectedAssignmentPointerSha256: "f".repeat(64) }));
      assert.equal(response.status, 409);
      assert.equal((await response.json()).error.code, "quick_forecast_assignment_conflict");
      assert.equal((await readdir(path.join(fixture.runtime, "jobs", "pending"))).length, 0);
    });
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test("reserved marker without a visible job reports publication in progress", { timeout: 420_000, skip: !pythonAvailable }, async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "b9-quick-in-progress-"));
  try {
    const fixture = createFixture(path.join(temporary, "fixture"), "ridge_regression");
    await withRuntime(fixture.runtime, async () => {
      const started = await queueQuickForecast(requestFor(fixture));
      const value = await started.json();
      await unlink(path.join(fixture.runtime, "jobs", "pending", `${value.jobId}.json`));
      const response = await queueQuickForecast(requestFor(fixture));
      assert.equal(response.status, 409);
      assert.equal((await response.json()).error.code, "quick_forecast_publication_in_progress");
    });
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test("conflicting and malformed exclusive markers fail closed", { timeout: 420_000, skip: !pythonAvailable }, async () => {
  for (const malformed of [false, true]) {
    const temporary = await mkdtemp(path.join(tmpdir(), "b9-quick-marker-integrity-"));
    try {
      const fixture = createFixture(path.join(temporary, "fixture"), "ridge_regression");
      const markerPath = path.join(fixture.runtime, "workspaces", fixture.workspaceId, "metadata", "quick_forecast_started.json");
      await writeFile(markerPath, malformed ? "not-json" : JSON.stringify({
        schemaVersion: "2.0",
        workflowType: "quick_forecast",
        workspaceId: fixture.workspaceId,
        datasetId: "f".repeat(64),
        deploymentId: "dhaka_south",
        validationRecordSha256: fixture.validationRecordSha256,
        expectedAssignmentPointerSha256: fixture.authority.authoritySnapshotSha256,
        assignmentId: fixture.authority.assignmentId,
        authoritySnapshotSha256: fixture.authority.authoritySnapshotSha256,
        jobId: "00000000-0000-4000-8000-000000000001",
        runId: "00000000-0000-4000-8000-000000000002",
        statusUrl: "/api/runtime/jobs/00000000-0000-4000-8000-000000000001",
        createdAt: new Date().toISOString(),
      }));
      await withRuntime(fixture.runtime, async () => {
        const response = await queueQuickForecast(requestFor(fixture));
        assert.equal(response.status, 409);
        assert.equal((await response.json()).error.code, "quick_forecast_start_integrity_error");
        assert.equal((await readdir(path.join(fixture.runtime, "jobs", "pending"))).length, 0);
      });
    } finally {
      await rm(temporary, { recursive: true, force: true });
    }
  }
});

test("anonymous and cross-origin requests fail before runtime initialization", async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "b9-quick-auth-"));
  try {
    const fixture = {
      workspaceId: "00000000-0000-4000-8000-000000000000",
      datasetId: "0".repeat(64),
      validationRecordSha256: "0".repeat(64),
      expectedAssignmentPointerSha256: "1".repeat(64),
    };
    await withRuntime(temporary, async () => {
      const anonymous = await queueQuickForecast(requestFor(fixture, {}, "anonymous"));
      assert.equal(anonymous.status, 401);
      const crossOrigin = await queueQuickForecast(requestFor(fixture, {}, "cross_origin"));
      assert.equal(crossOrigin.status, 403);
      assert.deepEqual(await readdir(temporary), []);
    });
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

test("route binds current Quick Forecast policy to the trusted lifecycle authority", async () => {
  const source = await readFile(new URL("../app/api/runtime/runs/quick/route.ts", import.meta.url), "utf8");
  assert.match(source, /loadCurrentModelLifecyclePolicy/);
  assert.match(source, /allowedQuickForecastPolicyVersion\s*!==\s*policy\.policyVersion/);
  assert.match(source, /allowedQuickForecastPolicySha256\s*!==\s*policyHash/);
  assert.match(source, /policy\.policySha256\s*!==\s*policyHash/);
  assert.doesNotMatch(source, /policy\.policyVersion\s*!==\s*["']p2-v[0-9]+["']/);
});

test("frontend handoff is gated on completed committed run and exact current authority", async () => {
  const source = await readFile(new URL("../components/forecast/QuickForecastRunPanel.tsx", import.meta.url), "utf8");
  assert.match(source, /job\.status === "completed"/);
  assert.match(source, /job\.committedRunId !== expectedRunId/);
  assert.match(source, /latest\.runId === committedRunId/);
  assert.match(source, /state\.status !== "current_verified"/);
  assert.match(source, /router\.push\("\/dashboard"\)/);
  assert.doesNotMatch(source, /EventSource|WebSocket/);
});

test("uploaded dashboard uses explicit unavailable states", async () => {
  const source = await readFile(new URL("../lib/runtime/dashboard-reader.ts", import.meta.url), "utf8");
  assert.match(source, /availabilityStatus: value\.forecast\.uncertaintyStatus/);
  assert.match(source, /lower: calibrated \? value\.forecast\.empiricalLower : null/);
  assert.match(source, /historicalCoverage: calibrated \? value\.forecast\.historicalCoverage : null/);
  assert.match(source, /preparedness: operational\?\{/);
  assert.match(source, /availabilityStatus:calculating\?"calculating":value\.preparedness\.availabilityStatus/);
  assert.doesNotMatch(source, /53\s*[â€“-]\s*187|87\s*\/\s*120\s*\/\s*153/);
});
