import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";

import {
  resolveActiveModel,
  resolveActiveModelP2V2,
  resolveHistoricalActiveModelP2V1
} from "../lib/runtime/active-model.ts";
import {
  loadModelLifecyclePolicy,
  loadModelLifecyclePolicyByIdentity
} from "../lib/runtime/model-lifecycle-policy.ts";

const REPO_ROOT = path.resolve(".");

test("TS Cross-Version Routing - p2-v2 unassigned throws active_model_not_assigned", async () => {
  const tmpRuntime = await fs.mkdtemp(path.join(os.tmpdir(), "ts-v2-test-"));
  try {
    await assert.rejects(
      async () => {
        await resolveActiveModelP2V2({
          repositoryRoot: REPO_ROOT,
          runtimeRoot: tmpRuntime,
          deploymentId: "dhaka_south"
        });
      },
      (err) => {
        assert.equal(err.code, "active_model_not_assigned");
        return true;
      }
    );
  } finally {
    await fs.rm(tmpRuntime, { recursive: true, force: true });
  }
});

test("TS Cross-Version Routing - resolveActiveModel delegates strictly to p2-v2", async () => {
  const tmpRuntime = await fs.mkdtemp(path.join(os.tmpdir(), "ts-v2-test-"));
  try {
    await assert.rejects(
      async () => {
        await resolveActiveModel(REPO_ROOT, tmpRuntime, "dhaka_south");
      },
      (err) => {
        assert.equal(err.code, "active_model_not_assigned");
        return true;
      }
    );
  } finally {
    await fs.rm(tmpRuntime, { recursive: true, force: true });
  }
});

test("TS Cross-Version Routing - p2-v1 historical fallback succeeds when empty", async () => {
  const tmpRuntime = await fs.mkdtemp(path.join(os.tmpdir(), "ts-v1-test-"));
  try {
    const res = await resolveHistoricalActiveModelP2V1({
      repositoryRoot: REPO_ROOT,
      runtimeRoot: tmpRuntime,
      deploymentId: "dhaka_south"
    });
    assert.equal(res.authoritySource, "historical_profile_fallback_pending_explicit_bootstrap");
    assert.equal(res.bootstrapRequired, true);
  } finally {
    await fs.rm(tmpRuntime, { recursive: true, force: true });
  }
});

test("TS Policy Loader - explicit p2-v1 and p2-v2 versions succeed", async () => {
  const p1 = await loadModelLifecyclePolicy({
    repositoryRoot: REPO_ROOT,
    deploymentId: "dhaka_south",
    version: "p2-v1"
  });
  assert.equal(p1.policy_version || p1.policyVersion, "p2-v1");

  const p2 = await loadModelLifecyclePolicy({
    repositoryRoot: REPO_ROOT,
    deploymentId: "dhaka_south",
    version: "p2-v2"
  });
  assert.equal(p2.policyVersion, "p2-v2");
});

test("TS Policy Loader - invalid raw hash fails closed", async () => {
  await assert.rejects(
    async () => {
      await loadModelLifecyclePolicyByIdentity({
        repositoryRoot: REPO_ROOT,
        deploymentId: "dhaka_south",
        policyId: "RUNTIME.MODEL_LIFECYCLE.DECISION",
        policyVersion: "p2-v1",
        expectedCanonicalSha256: "570a931bc2e98ca5cada78c5fe891e699e43e7c9f513b8df2257c06f1261b7bb",
        expectedRawSha256: "invalid_raw_hash_here"
      });
    },
    (err) => {
      return true;
    }
  );
});
