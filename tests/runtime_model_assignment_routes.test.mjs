import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import test from "node:test";

const runFile = promisify(execFile);
const root = path.resolve(import.meta.dirname, "..");
const python = process.env.DENGUEOPS_TEST_PYTHON
  || process.env.PYTHON
  || "C:\\Users\\CUBE\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";
const sessionSecret = "assignment-route-isolated-session-secret-value";
const sha = value => createHash("sha256").update(value).digest("hex");

async function buildFixture(modelId, override) {
  const base = await mkdtemp(path.join(tmpdir(), "dengueops-b94a-route-fixture-"));
  const script = String.raw`
import json, shutil, sys
from pathlib import Path
root=Path(sys.argv[1])
base=Path(sys.argv[2])
model_id=sys.argv[3]
override=sys.argv[4]=="true"
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/"analytics"))
from tests.lifecycle_fixtures import build_one_run_chain_p2_v2
from runtime_model_lifecycle_commit import commit_lifecycle_action
from runtime_commit import sha256_file
prior=build_one_run_chain_p2_v2(base/"prior",root,model_id="extra_trees",override=False)
published=commit_lifecycle_action(prior["runtime"],prior["runId"],"Prior isolated assignment.","prior-operator",True,root)
assert published["success"],published
target=build_one_run_chain_p2_v2(base/"target",root,model_id=model_id,override=override)
runtime=target["runtime"]
shutil.copytree(prior["runtime"]/"model-assignments",runtime/"model-assignments",dirs_exist_ok=True)
source_pointer=prior["runtime"]/"deployments/dhaka_south/model-assignment/latest.json"
target_pointer=runtime/"deployments/dhaka_south/model-assignment/latest.json"
target_pointer.parent.mkdir(parents=True,exist_ok=True)
shutil.copyfile(source_pointer,target_pointer)
commit=runtime/"runs"/target["runId"]/"metadata/commit.json"
print(json.dumps({"runtime":str(runtime),"runId":target["runId"],"commitSha":sha256_file(commit),"pointerSha":sha256_file(target_pointer),"priorAssignmentId":published["assignmentId"]}))
`;
  const { stdout } = await runFile(python, ["-c", script, root, base, modelId, String(override)], {
    cwd: root,
    timeout: 420_000,
    maxBuffer: 1024 * 1024,
    windowsHide: true,
  });
  return { base, ...JSON.parse(stdout.trim().split(/\r?\n/).at(-1)) };
}

async function invokeRoute(runtime, body, options = {}) {
  const script = String.raw`
const sessionModule=await import("./lib/auth/session.ts");
const routeModule=await import("./app/api/runtime/model-assignments/route.ts");
const {createSessionToken,sessionCookieName}=sessionModule.default||sessionModule;
const {POST}=routeModule.default||routeModule;
const headers=new Headers({"content-type":"application/json","host":"localhost:3000"});
if(process.env.TEST_AUTH==="true"){
  const token=await createSessionToken("isolated-super-user");
  headers.set("cookie",sessionCookieName()+"="+token);
  headers.set("origin",process.env.TEST_ORIGIN||"http://localhost:3000");
}
const request=new Request("http://localhost:3000/api/runtime/model-assignments",{
  method:"POST",headers,body:process.env.TEST_BODY
});
const response=await POST(request);
console.log(JSON.stringify({status:response.status,body:await response.json()}));
`;
  const { stdout } = await runFile(process.execPath, [
    "--conditions=react-server",
    "--import", "tsx",
    "-e", script,
  ], {
    cwd: root,
    env: {
      ...process.env,
      DENGUEOPS_RUNTIME_ROOT: runtime,
      DENGUEOPS_PYTHON_EXECUTABLE: python,
      DENGUEOPS_SESSION_SECRET: sessionSecret,
      TEST_AUTH: String(options.auth === true),
      TEST_ORIGIN: options.origin || "",
      TEST_BODY: typeof body === "string" ? body : JSON.stringify(body),
    },
    timeout: 180_000,
    maxBuffer: 256 * 1024,
    windowsHide: true,
  });
  return JSON.parse(stdout.trim().split(/\r?\n/).at(-1));
}

function requestBody(fixture, overrides = {}) {
  return {
    approvedForecastRunId: fixture.runId,
    expectedApprovedForecastCommitSha256: fixture.commitSha,
    expectedAssignmentPointerSha256: fixture.pointerSha,
    reason: "Assign the candidate from the verified approved one-run forecast.",
    assignmentAcknowledged: true,
    ...overrides,
  };
}

test("assignment route is bounded, server-derived, locked, and post-verifies publication", async () => {
  const source = await readFile(path.join(root, "app/api/runtime/model-assignments/route.ts"), "utf8");
  assert.match(source, /await requireSuperUserMutation\(request\)[\s\S]*await request\.json\(\)/);
  assert.match(source, /assignment_pointer_conflict/);
  assert.match(source, /\.publication-lock/);
  assert.match(source, /await verifiedPointer\(config, expectedAssignmentPointerSha256\)[\s\S]*runFile/);
  assert.match(source, /resolveActiveModelP2V2/);
  assert.match(source, /sourceApprovedForecastRunId/);
  assert.doesNotMatch(source, /authorizeSuperUserOrService|model-lifecycle/);
  assert.doesNotMatch(source, /body\.(candidateId|modelId|assessmentId|decisionId|authorizationId)/);
});

test("anonymous, cross-origin, malformed, and client-selected model requests fail before publication", { timeout: 90_000 }, async () => {
  const runtime = await mkdtemp(path.join(tmpdir(), "dengueops-b94a-route-empty-"));
  try {
    assert.equal((await invokeRoute(runtime, "{not-json")).status, 401);
    assert.equal((await invokeRoute(runtime, {}, { auth: true, origin: "https://attacker.invalid" })).status, 403);
    for (const body of [
      {},
      requestBody({ runId: "00000000-0000-4000-8000-000000000000", commitSha: "0".repeat(64), pointerSha: "1".repeat(64) }, { assignmentAcknowledged: false }),
      requestBody({ runId: "00000000-0000-4000-8000-000000000000", commitSha: "0".repeat(64), pointerSha: "1".repeat(64) }, { reason: "x".repeat(1001) }),
    ]) {
      assert.equal((await invokeRoute(runtime, body, { auth: true })).status, 400);
    }
  } finally {
    await rm(runtime, { recursive: true, force: true });
  }
});

test("arbitrary client candidate and model identifiers are separately rejected", async () => {
  const runtime = await mkdtemp(path.join(tmpdir(), "dengueops-b94a-route-model-rejection-"));
  try {
    const fixture = {
      runId: "00000000-0000-4000-8000-000000000000",
      commitSha: "0".repeat(64),
      pointerSha: "1".repeat(64),
    };
    for (const extra of [{ candidateId: "poisson_gam" }, { modelId: "random_forest" }]) {
      const response = await invokeRoute(runtime, { ...requestBody(fixture), ...extra }, { auth: true });
      assert.equal(response.status, 400);
      assert.equal(response.body.error.code, "invalid_assignment_request");
    }
  } finally {
    await rm(runtime, { recursive: true, force: true });
  }
});

test("winner publication enforces pointer concurrency and returns a sanitized verified response", { timeout: 600_000 }, async () => {
  const fixture = await buildFixture("extra_trees", false);
  try {
    const pointerPath = path.join(fixture.runtime, "deployments/dhaka_south/model-assignment/latest.json");
    const before = await readFile(pointerPath);
    const stale = await invokeRoute(
      fixture.runtime,
      requestBody(fixture, { expectedAssignmentPointerSha256: "0".repeat(64) }),
      { auth: true },
    );
    assert.equal(stale.status, 409);
    assert.equal(stale.body.error.code, "assignment_pointer_conflict");
    assert.deepEqual(await readFile(pointerPath), before);

    const lockPath = path.join(fixture.runtime, "deployments/dhaka_south/model-assignment/.publication-lock");
    await mkdir(lockPath);
    const locked = await invokeRoute(fixture.runtime, requestBody(fixture), { auth: true });
    assert.equal(locked.status, 409);
    assert.equal(locked.body.error.code, "assignment_publication_in_progress");
    await readFile(path.join(lockPath, "..", "latest.json"));
    await rm(lockPath, { recursive: true });

    const accepted = await invokeRoute(fixture.runtime, requestBody(fixture), { auth: true });
    assert.equal(accepted.status, 201);
    const value = accepted.body;
    assert.deepEqual(Object.keys(value).sort(), [
      "assignmentId", "createdAt", "ok", "previousAssignmentPresent", "selectedCandidateId",
      "selectedCandidateLabel", "sourceApprovedForecastRunId", "status",
    ]);
    assert.equal(value.selectedCandidateId, "extra_trees");
    assert.equal(value.sourceApprovedForecastRunId, fixture.runId);
    assert.equal(value.previousAssignmentPresent, true);
    assert.equal(value.status, "assigned");
    assert.notEqual(sha(await readFile(pointerPath)), fixture.pointerSha);
  } finally {
    await rm(fixture.base, { recursive: true, force: true });
  }
});

test("governed eligible non-winner approved run is assigned without a client model identity", { timeout: 600_000 }, async () => {
  const fixture = await buildFixture("random_forest", true);
  try {
    const response = await invokeRoute(fixture.runtime, requestBody(fixture), { auth: true });
    assert.equal(response.status, 201);
    assert.equal(response.body.selectedCandidateId, "random_forest");
    assert.equal("modelId" in response.body, false);
    assert.equal("candidateId" in response.body, false);
  } finally {
    await rm(fixture.base, { recursive: true, force: true });
  }
});
