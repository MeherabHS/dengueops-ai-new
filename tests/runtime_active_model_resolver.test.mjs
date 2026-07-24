import test from "node:test";
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { cp, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import activeModelModule from "../lib/runtime/active-model.ts";
import { spawnPythonSync } from "./node_python_runner.mjs";

const { resolveActiveModel } = activeModelModule;
const ROOT = path.resolve(".");
const sha = value => createHash("sha256").update(value).digest("hex");

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

for (const modelId of ["random_forest", "ridge_regression"]) {
  test(`Python and TypeScript resolve identical ${modelId} current authority`, { timeout: 360_000 }, async () => {
    const temporary = await mkdtemp(path.join(tmpdir(), `b6-${modelId}-`));
    try {
      const fixture = pythonFixture(path.join(temporary, "fixture"), modelId);
      const typescript = await resolveActiveModel(ROOT, fixture.runtime, "dhaka_south");
      assert.deepEqual(typescript, fixture.authority);
      assert.match(typescript.assignmentCommitSha256, /^[a-f0-9]{64}$/);
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
