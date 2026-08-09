import test from "node:test";
import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import Module from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { require as tsxRequire } from "tsx/cjs/api";
import { findPython } from "./node_python_runner.mjs";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const runFile = promisify(execFile);
const root = path.resolve(import.meta.dirname, "..");
const python = process.env.DENGUEOPS_TEST_PYTHON || findPython().command;

const originalModuleLoad = Module._load;
Module._load = function loadAssessmentJobRoute(request, parent, isMain) {
  if (request === "server-only") return {};
  return originalModuleLoad.call(this, request, parent, isMain);
};
const jobRouteImported = tsxRequire("../app/api/runtime/jobs/[jobId]/route.ts", import.meta.url);
Module._load = originalModuleLoad;
const { GET: getRuntimeJob } = jobRouteImported.default ?? jobRouteImported;

test("dataset-assessment job GET returns only a server-verified dynamic candidate count", async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "assessment-job-count-"));
  const previousRuntimeRoot = process.env.DENGUEOPS_RUNTIME_ROOT;
  const previousPython = process.env.DENGUEOPS_PYTHON_EXECUTABLE;
  try {
    process.env.DENGUEOPS_RUNTIME_ROOT = temporary;
    process.env.DENGUEOPS_PYTHON_EXECUTABLE = process.execPath;
    const pending = path.join(temporary, "jobs", "pending");
    await mkdir(pending, { recursive: true });
    const registryBytes = await readFile(path.join(root, "config", "candidate_models.json"));
    const registry = JSON.parse(registryBytes.toString("utf8"));
    const policy = JSON.parse(await readFile(path.join(root, "config", "deployments", "dhaka_south", "assessment_policy.json"), "utf8"));
    const jobId = "11111111-1111-4111-8111-111111111111";
    const assessmentId = "22222222-2222-4222-8222-222222222222";
    const jobPath = path.join(pending, `${jobId}.json`);
    const job = {
      schemaVersion: "1.0", jobKind: "dataset_assessment", jobId, assessmentId,
      workspaceId: "33333333-3333-4333-8333-333333333333", datasetId: "a".repeat(64),
      deploymentId: "dhaka_south", workflowMode: "assess_dataset", validationRecordSha256: "b".repeat(64),
      assessmentPolicyId: policy.policy_id, assessmentPolicyVersion: policy.policy_version,
      assessmentPolicySha256: policy.policy_sha256,
      candidateRegistrySha256: createHash("sha256").update(registryBytes).digest("hex"),
      status: "running", progress: "evaluating_candidates", createdAt: "2026-08-01T00:00:00.000Z",
      claimedAt: "2026-08-01T00:00:01.000Z", startedAt: "2026-08-01T00:00:01.000Z",
      updatedAt: "2026-08-01T00:00:02.000Z", completedAt: null, heartbeatAt: "2026-08-01T00:00:02.000Z",
      workerId: "test-worker", processId: 1, timeoutSeconds: 1800, retryCount: 0, error: null,
      committedAssessmentId: null,
    };
    await writeFile(jobPath, JSON.stringify(job));
    const verifiedResponse = await getRuntimeJob(new Request(`http://localhost/api/runtime/jobs/${jobId}`), { params: Promise.resolve({ jobId }) });
    assert.equal(verifiedResponse.status, 200);
    const verified = await verifiedResponse.json();
    assert.equal(verified.verifiedCandidateCount, registry.candidates.length);
    assert.notEqual(registry.candidates.length, 0);

    await writeFile(jobPath, JSON.stringify({ ...job, candidateRegistrySha256: "0".repeat(64) }));
    const mismatchResponse = await getRuntimeJob(new Request(`http://localhost/api/runtime/jobs/${jobId}`), { params: Promise.resolve({ jobId }) });
    assert.equal(mismatchResponse.status, 200);
    const mismatch = await mismatchResponse.json();
    assert.equal("verifiedCandidateCount" in mismatch, false);
  } finally {
    if (previousRuntimeRoot === undefined) delete process.env.DENGUEOPS_RUNTIME_ROOT;
    else process.env.DENGUEOPS_RUNTIME_ROOT = previousRuntimeRoot;
    if (previousPython === undefined) delete process.env.DENGUEOPS_PYTHON_EXECUTABLE;
    else process.env.DENGUEOPS_PYTHON_EXECUTABLE = previousPython;
    await rm(temporary, { recursive: true, force: true });
  }
});

test("assessment start uses the schema-verified current policy and registry without a fixed candidate set", async () => {
  const source = await read("app/api/runtime/assessments/route.ts");
  assert.match(source, /export const runtime = "nodejs"/);
  assert.match(source, /workspaceId.*datasetId.*deploymentId.*validationRecordSha256/s);
  assert.match(source, /unexpected_assessment_field/);
  assert.match(source, /full_assessment_eligible/);
  assert.match(source, /runtime_assessment_policy\.schema\.json/);
  assert.match(source, /candidate_models\.schema\.json/);
  assert.match(source, /feature_availability_policy\.json/);
  assert.match(source, /validateStrictJsonSchema/);
  assert.match(source, /registryById/);
  assert.match(source, /governedCandidates\.length === registryCandidates\.length/);
  assert.match(source, /registryIds\.some\(candidateId => assess\.candidateEligibility/);
  assert.match(source, /minimumFoldCount/);
  assert.match(source, /maximumFoldCount/);
  assert.match(source, /expectedPlannedFoldCount = Math\.min\(expectedAvailableFoldCount, maximumFoldCount\)/);
  assert.match(source, /temporalValidationPolicySha256: temporalPolicyHash/);
  assert.match(source, /validation\.temporalValidation\?\.purgeGapWeeks !== effectivePurgeRows/);
  assert.doesNotMatch(source, /governedCandidates\.length === 7|registryCandidates\.length === 7/);
  assert.doesNotMatch(source, /policy\.policy_version !== "p2-v[123]"/);
  assert.doesNotMatch(source, /labelledRows\s*!==\s*173|availableFoldCount\s*!==\s*68/);
  assert.doesNotMatch(source, /spawn\(|exec\(|candidateIds\s*:|technicalWinner\s*:/);
});

test("assessment evidence presents bounded temporal validation without claiming an untouched holdout", async () => {
  const component = await read("components/validation/RuntimeAssessmentWorkflow.tsx");
  assert.match(component, /Temporal validation/);
  assert.match(component, /Rolling-origin assessment/);
  assert.match(component, /Leakage checks/);
  assert.match(component, /Latest retrospective snapshot/);
  assert.match(component, /not an untouched scientific holdout/);
});

test("current assessment authority binds every current registry candidate and its exact identities", async () => {
  const policy = JSON.parse(await read("config/deployments/dhaka_south/assessment_policy.json"));
  const registry = JSON.parse(await read("config/candidate_models.json"));
  const policyIds = policy.candidate_eligibility_policy.candidates.map(candidate => candidate.model_id);
  const registryIds = registry.candidates.map(candidate => candidate.model_id);
  assert.equal(policy.policy_id, "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE");
  assert.equal(policy.policy_version, "p2-v3");
  assert.equal(registry.candidate_registry_version, "p2-v2");
  assert.equal(registryIds.length, 11);
  assert.deepEqual(policyIds, registryIds);
  assert.ok(registryIds.includes("poisson_gam"));
  assert.ok(registryIds.includes("extra_trees"));
  for (const governed of policy.candidate_eligibility_policy.candidates) {
    const registered = registry.candidates.find(candidate => candidate.model_id === governed.model_id);
    assert.equal(governed.parameters_sha256, registered?.parameters_sha256);
  }
});

test("assessment request candidate injection remains prohibited before durable enqueue", async () => {
  const source = await read("app/api/runtime/assessments/route.ts");
  assert.match(source, /allowed = new Set\(\["workspaceId", "datasetId", "deploymentId", "validationRecordSha256"\]\)/);
  assert.match(source, /await requireSuperUserMutation\(request\)[\s\S]*await readBoundedJson/);
  assert.match(source, /sha256\(registryBytes\) !== policy\.candidate_registry\?\.sha256/);
  assert.match(source, /registry\.candidate_registry_version !== policy\.candidate_registry\?\.version/);
  assert.match(source, /assess\.policyVersion !== policy\.policy_version/);
});

test("current p2-v3 assessment request queues against the registry-derived eleven-candidate fixture", { timeout: 120_000 }, async () => {
  const base = await mkdtemp(path.join(tmpdir(), "dengueops-b94a-assessment-route-"));
  try {
    const fixtureScript = String.raw`
import json, sys
from pathlib import Path
root=Path(sys.argv[1]); base=Path(sys.argv[2])
sys.path.insert(0,str(root)); sys.path.insert(0,str(root/"analytics"))
from tests.test_runtime_assessment_commit import build_ready_assessment_runtime
from runtime_commit import sha256_file
runtime,workspace,pending,job=build_ready_assessment_runtime(base,assessment_policy_version="p2-v3")
pending.unlink()
print(json.dumps({"runtime":str(runtime),"workspaceId":job["workspaceId"],"datasetId":job["datasetId"],"validationRecordSha256":job["validationRecordSha256"]}))
`;
    const fixtureResult = await runFile(python, ["-c", fixtureScript, root, base], {
      cwd: root, timeout: 90_000, encoding: "utf8", windowsHide: true,
    });
    const fixture = JSON.parse(fixtureResult.stdout.trim().split(/\r?\n/).at(-1));
    const body = {
      workspaceId: fixture.workspaceId,
      datasetId: fixture.datasetId,
      deploymentId: "dhaka_south",
      validationRecordSha256: fixture.validationRecordSha256,
    };
    const routeScript = String.raw`
const sessionModule=await import("./lib/auth/session.ts");
const routeModule=await import("./app/api/runtime/assessments/route.ts");
const {createSessionToken,sessionCookieName}=sessionModule.default||sessionModule;
const {POST}=routeModule.default||routeModule;
const token=await createSessionToken("isolated-assessment-super-user");
const response=await POST(new Request("http://localhost:3000/api/runtime/assessments",{
  method:"POST",
  headers:{"content-type":"application/json","host":"localhost:3000","origin":"http://localhost:3000","cookie":sessionCookieName()+"="+token},
  body:process.env.TEST_BODY
}));
console.log(JSON.stringify({status:response.status,body:await response.json()}));
`;
    const routeResult = await runFile(process.execPath, ["--conditions=react-server", "--import", "tsx", "-e", routeScript], {
      cwd: root,
      env: {
        ...process.env,
        DENGUEOPS_RUNTIME_ROOT: fixture.runtime,
        DENGUEOPS_PYTHON_EXECUTABLE: python,
        DENGUEOPS_SESSION_SECRET: "assessment-route-isolated-session-secret-value",
        TEST_BODY: JSON.stringify(body),
      },
      timeout: 30_000,
      encoding: "utf8",
      windowsHide: true,
    });
    const response = JSON.parse(routeResult.stdout.trim().split(/\r?\n/).at(-1));
    assert.equal(response.status, 202, JSON.stringify(response.body));
    assert.equal(response.body.status, "queued");
    const jobs = await readdir(path.join(fixture.runtime, "jobs", "pending"));
    assert.equal(jobs.length, 1);
    const job = JSON.parse(await readFile(path.join(fixture.runtime, "jobs", "pending", jobs[0]), "utf8"));
    const registry = JSON.parse(await read("config/candidate_models.json"));
    assert.equal(job.assessmentPolicyVersion, "p2-v3");
    assert.equal(registry.candidates.length, 11);
    assert.ok(registry.candidates.some(candidate => candidate.model_id === "poisson_gam"));
    assert.ok(registry.candidates.some(candidate => candidate.model_id === "extra_trees"));
  } finally {
    await rm(base, { recursive: true, force: true });
  }
});

test("assessment result is compact, hash-verified, and no-store", async () => {
  const source = await read("app/api/runtime/assessments/[assessmentId]/route.ts");
  assert.match(source, /readVerifiedAssessment/);
  assert.match(source, /assessmentSummarySha256/);
  assert.match(source, /Cache-Control.*no-store/s);
  assert.doesNotMatch(source, /rolling_validation\.json|uploaded rows|stdout\.log/);
});

test("assessment result adds governed order and redacted workflow state", async () => {
  const source = await read("app/api/runtime/assessments/[assessmentId]/route.ts");
  assert.match(source, /deriveAssessmentDisplayOrder/);
  assert.match(source, /displayRank/);
  assert.match(source, /technicalWinnerDeployable/);
  assert.match(source, /currentApprovedModel/);
  assert.match(source, /readVerifiedAssessmentDecisionState/);
  assert.match(source, /authorizationStatus/);
  assert.match(source, /committedRunId/);
  assert.match(source, /assessmentPolicy/);
  assert.match(source, /phase2_decision_policy_available/);
  assert.match(source, /loadDecisionPolicy/);
  assert.match(source, /plannedFoldCount/);
  assert.match(source, /selectedEvaluationPeriod/);
  assert.doesNotMatch(source, /operatorIdentifier|internalDecisionSecret|reason:/);
});

test("frontend assessment completion never refreshes Overview", async () => {
  const source = await read("components/forecast/ForecastRunWorkflow.tsx");
  assert.match(source, /startDatasetAssessment/);
  assert.match(source, /committedAssessmentId/);
  assert.match(source, /assessment_completed/);
  const assessmentBranch = source.slice(source.indexOf("const runAssessment"), source.indexOf("const recordDecision"));
  assert.doesNotMatch(assessmentBranch, /getLatestDashboard|location\.assign|sessionStorage/);
});
