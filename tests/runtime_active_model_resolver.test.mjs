import test from "node:test";
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import activeModelModule from "../lib/runtime/active-model.ts";
import modelLifecyclePolicyModule from "../lib/runtime/model-lifecycle-policy.ts";
import { spawnPythonSync } from "./node_python_runner.mjs";

const { resolveActiveModel } = activeModelModule;
const { loadModelLifecyclePolicy } = modelLifecyclePolicyModule;
const ROOT = path.resolve(".");
const sha = value => createHash("sha256").update(value).digest("hex");
const CURRENT_ASSIGNMENT_ID = "e855f7ef-92c9-422c-be8d-4011ab5acb04";

async function writeCurrentAssignmentFixture(runtime) {
  const [registryBytes, policyBytes] = await Promise.all([
    readFile(path.join(ROOT, "config", "candidate_models.json")),
    readFile(path.join(ROOT, "config", "deployments", "dhaka_south", "model_lifecycle_policy.json")),
  ]);
  const registry = JSON.parse(registryBytes);
  const policy = JSON.parse(policyBytes);
  const candidate = registry.candidates.find(value => value.model_id === "poisson_gam");
  const assignmentRoot = path.join(runtime, "model-assignments", CURRENT_ASSIGNMENT_ID);
  await mkdir(path.join(assignmentRoot, "artifacts"), { recursive: true });
  await mkdir(path.join(assignmentRoot, "metadata"), { recursive: true });
  const record = {
    schemaVersion: "2.0",
    assignmentId: CURRENT_ASSIGNMENT_ID,
    deploymentId: "dhaka_south",
    assignmentAction: "assign_selected_model",
    modelId: candidate.model_id,
    modelFamily: candidate.model_family,
    parameterSha256: candidate.parameters_sha256,
    preprocessingIdentity: candidate.preprocessing_identity,
    candidateRegistrySha256: sha(registryBytes),
    featureOrderSha256: candidate.feature_order_sha256,
    foldPlanSha256: "7".repeat(64),
    sourceAssessmentId: "1e25afe1-3225-41b6-995a-fb50aafce05c",
    sourceDecisionId: "9c8f3a96-86b2-4b44-a93b-b08080740100",
    sourceAuthorizationId: "109bd6f4-73fa-4a73-adef-407384697205",
    sourceApprovedForecastRunId: "80b003f9-6cf7-4b5e-8df6-8fd46a0f68b2",
    priorAssignmentId: null,
    priorAssignmentCommitSha256: null,
    operatorIdentifier: "focused-parity-test",
    reason: "Verify current assignment policy parity.",
    assignedAt: "2026-07-28T13:40:24.456765Z",
  };
  const recordBytes = Buffer.from(`${JSON.stringify(record, null, 2)}\n`);
  await writeFile(path.join(assignmentRoot, "artifacts", "assignment_record.json"), recordBytes);
  const commit = {
    schemaVersion: "2.0",
    assignmentId: CURRENT_ASSIGNMENT_ID,
    assignmentRecordSha256: sha(recordBytes),
    committedAt: record.assignedAt,
  };
  const commitBytes = Buffer.from(`${JSON.stringify(commit, null, 2)}\n`);
  await writeFile(path.join(assignmentRoot, "metadata", "commit.json"), commitBytes);
  const pointer = {
    schemaVersion: "2.0",
    deploymentId: "dhaka_south",
    assignmentId: CURRENT_ASSIGNMENT_ID,
    assignmentAction: "assign_selected_model",
    assignedModelId: candidate.model_id,
    modelFamily: candidate.model_family,
    parameterSha256: candidate.parameters_sha256,
    featureOrderSha256: candidate.feature_order_sha256,
    candidateRegistrySha256: sha(registryBytes),
    policyId: policy.policyId,
    policyVersion: policy.policyVersion,
    policySha256: policy.policySha256,
    sourceDecisionId: record.sourceDecisionId,
    sourceDecisionCommitSha256: "a".repeat(64),
    assignmentCommitSha256: sha(commitBytes),
    priorAssignmentId: null,
    priorAssignmentCommitSha256: null,
    publishedAt: record.assignedAt,
    activeModelAuthority: "committed_assignment",
    automaticAction: false,
  };
  const pointerPath = path.join(runtime, "deployments", "dhaka_south", "model-assignment", "latest.json");
  await mkdir(path.dirname(pointerPath), { recursive: true });
  await writeFile(pointerPath, `${JSON.stringify(pointer, null, 2)}\n`);
  return pointerPath;
}

function pythonFixture(base, modelId) {
  const result = spawnPythonSync(
    ["-m", "tests.runtime_active_model_parity_probe", "create", base, modelId],
    { timeout: 300_000 },
  );
  assert.equal(result.status, 0, result.stdout + result.stderr);
  return JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
}

async function expectIntegrity(runtime) {
  await assert.rejects(
    resolveActiveModel(ROOT, runtime, "dhaka_south"),
    error => error.code === "active_model_integrity_error",
  );
}

test("verified current p2-v3 poisson_gam assignment resolves and stale or tampered policy fails closed", async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "b85-current-parity-"));
  try {
    const runtime = path.join(temporary, "runtime");
    await writeCurrentAssignmentFixture(runtime);
    const resolved = await resolveActiveModel(ROOT, runtime, "dhaka_south");
    assert.equal(resolved.assignmentId, CURRENT_ASSIGNMENT_ID);
    assert.equal(resolved.modelId, "poisson_gam");
    assert.equal(resolved.modelFamily, "SplinePoissonRegressor");
    assert.equal(resolved.lifecyclePolicyVersion, "p2-v3");
    assert.equal(resolved.authoritySource, "committed_assignment");

    for (const [field, value] of [
      ["policyVersion", "p2-v2"],
      ["policyVersion", "unsupported"],
      ["policySha256", "0".repeat(64)],
    ]) {
      const copy = path.join(temporary, `${field}-${value.slice(0, 8)}`);
      await cp(runtime, copy, { recursive: true });
      const copyPointer = path.join(copy, "deployments", "dhaka_south", "model-assignment", "latest.json");
      const changed = JSON.parse(await readFile(copyPointer, "utf8"));
      changed[field] = value;
      await writeFile(copyPointer, JSON.stringify(changed));
      await expectIntegrity(copy);
    }
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});

for (const modelId of ["random_forest", "ridge_regression"]) {
  test(`Python and TypeScript resolve identical ${modelId} current authority`, { timeout: 360_000 }, async () => {
    const temporary = await mkdtemp(path.join(tmpdir(), `b6-${modelId}-`));
    try {
      const fixture = pythonFixture(path.join(temporary, "fixture"), modelId);
      const typescript = await resolveActiveModel(ROOT, fixture.runtime, "dhaka_south");
      assert.deepEqual(typescript, fixture.authority);
      assert.match(typescript.assignmentCommitSha256, /^[a-f0-9]{64}$/);
      assert.equal(typescript.lifecyclePolicyVersion, "p2-v3");
      assert.match(typescript.lifecyclePolicySha256, /^[a-f0-9]{64}$/);
      assert.match(typescript.authoritySnapshotSha256, /^[a-f0-9]{64}$/);
    } finally {
      await rm(temporary, { recursive: true, force: true });
    }
  });
}

test("current resolver fails closed for missing assignment and historical profile", async () => {
  const runtime = await mkdtemp(path.join(tmpdir(), "b6-unassigned-"));
  try {
    await assert.rejects(
      resolveActiveModel(ROOT, runtime, "dhaka_south"),
      error => error.code === "active_model_not_assigned",
    );
  } finally {
    await rm(runtime, { recursive: true, force: true });
  }
});

test("explicit archived p2-v2 policy remains readable without becoming current authority", async () => {
  const historical = await loadModelLifecyclePolicy({
    repositoryRoot: ROOT,
    deploymentId: "dhaka_south",
    version: "p2-v2",
  });
  assert.equal(historical.policyVersion, "p2-v2");
});

test("current resolver rejects pointer, commit, and registry identity tampering", { timeout: 360_000 }, async () => {
  const temporary = await mkdtemp(path.join(tmpdir(), "b6-tamper-"));
  try {
    const fixture = pythonFixture(path.join(temporary, "fixture"), "ridge_regression");
    const pointerPath = path.join(fixture.runtime, "deployments", "dhaka_south", "model-assignment", "latest.json");
    const originalPointer = await readFile(pointerPath);
    const pointer = JSON.parse(originalPointer);
    const assignmentRoot = path.join(fixture.runtime, "model-assignments", pointer.assignmentId);
    const recordPath = path.join(assignmentRoot, "artifacts", "assignment_record.json");
    const commitPath = path.join(assignmentRoot, "metadata", "commit.json");

    for (const mutate of [
      value => { value.assignmentCommitSha256 = "0".repeat(64); },
      value => { value.modelFamily = "WrongFamily"; },
      value => { value.parameterSha256 = "0".repeat(64); },
      value => { value.candidateRegistrySha256 = "0".repeat(64); },
      value => { value.policyVersion = "p2-v2"; },
      value => { value.policySha256 = "0".repeat(64); },
    ]) {
      const copy = path.join(temporary, randomUUID());
      await cp(fixture.runtime, copy, { recursive: true });
      const copyPointerPath = path.join(copy, "deployments", "dhaka_south", "model-assignment", "latest.json");
      const changed = JSON.parse(await readFile(copyPointerPath, "utf8"));
      mutate(changed);
      await writeFile(copyPointerPath, JSON.stringify(changed));
      await expectIntegrity(copy);
    }

    const commitTamper = path.join(temporary, "commit-tamper");
    await cp(fixture.runtime, commitTamper, { recursive: true });
    const copyCommit = path.join(commitTamper, "model-assignments", pointer.assignmentId, "metadata", "commit.json");
    const commit = JSON.parse(await readFile(copyCommit, "utf8"));
    commit.committedAt = "2020-01-01T00:00:00Z";
    await writeFile(copyCommit, JSON.stringify(commit));
    await expectIntegrity(commitTamper);

    for (const [field, value] of [
      ["modelFamily", "WrongFamily"],
      ["parameterSha256", "0".repeat(64)],
      ["preprocessingIdentity", "0".repeat(64)],
      ["candidateRegistrySha256", "0".repeat(64)],
    ]) {
      const copy = path.join(temporary, `record-${field}`);
      await cp(fixture.runtime, copy, { recursive: true });
      const copyRecordPath = path.join(copy, "model-assignments", pointer.assignmentId, "artifacts", "assignment_record.json");
      const copyCommitPath = path.join(copy, "model-assignments", pointer.assignmentId, "metadata", "commit.json");
      const copyPointerPath = path.join(copy, "deployments", "dhaka_south", "model-assignment", "latest.json");
      const record = JSON.parse(await readFile(copyRecordPath, "utf8"));
      record[field] = value;
      const recordBytes = Buffer.from(JSON.stringify(record));
      await writeFile(copyRecordPath, recordBytes);
      const commitValue = JSON.parse(await readFile(copyCommitPath, "utf8"));
      commitValue.assignmentRecordSha256 = sha(recordBytes);
      const commitBytes = Buffer.from(JSON.stringify(commitValue));
      await writeFile(copyCommitPath, commitBytes);
      const pointerValue = JSON.parse(await readFile(copyPointerPath, "utf8"));
      if (field !== "preprocessingIdentity") pointerValue[field === "modelFamily" ? "modelFamily" : field] = value;
      pointerValue.assignmentCommitSha256 = sha(commitBytes);
      await writeFile(copyPointerPath, JSON.stringify(pointerValue));
      await expectIntegrity(copy);
    }

    assert.ok(await readFile(recordPath));
    assert.ok(await readFile(commitPath));
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
});
