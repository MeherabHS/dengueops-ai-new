import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import crypto from "node:crypto";

import { resolveActiveModel, ActiveModelError } from "../lib/runtime/active-model-resolver.ts";

const ROOT = path.resolve(import.meta.dirname, "..");

test("TS Resolver: fails closed with active_model_not_assigned when no assignment exists under p2", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ts-resolver-test-"));
  try {
    assert.throws(
      () => resolveActiveModel(ROOT, tmpDir, "dhaka_south"),
      (err) => err instanceof ActiveModelError && err.message === "active_model_not_assigned"
    );
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});

test("TS Resolver: resolves valid committed assignment", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ts-resolver-valid-"));
  try {
    const pointerDir = path.join(tmpDir, "deployments", "dhaka_south", "model-assignment");
    const assignmentDir = path.join(tmpDir, "model-assignments", "test-assignment-123");
    fs.mkdirSync(pointerDir, { recursive: true });
    fs.mkdirSync(path.join(assignmentDir, "artifacts"), { recursive: true });
    fs.mkdirSync(path.join(assignmentDir, "metadata"), { recursive: true });

    const record = {
      schemaVersion: "2.0",
      assignmentId: "test-assignment-123",
      modelId: "ridge_regression",
      modelFamily: "Ridge",
      parameterSha256: "abc123456789",
      preprocessingIdentity: "canonical_identity",
      candidateRegistrySha256: "74cb3635c5e211874ee5ad23196fc95bfdfbdb5c6438cc3d060f0b9ff49acfa0",
      featureOrderSha256: "aeccbe517da452e1132f08c02599418523fb003280b11ff9cda66cfb3aa55a85",
      foldPlanSha256: "fold123",
      sourceAssessmentId: "ass1",
      sourceDecisionId: "dec1",
      sourceAuthorizationId: "auth1",
      sourceApprovedForecastRunId: "run1",
      assignedAt: new Date().toISOString()
    };

    const recordBuf = Buffer.from(JSON.stringify(record, null, 2));
    fs.writeFileSync(path.join(assignmentDir, "artifacts", "assignment_record.json"), recordBuf);

    const recSha = crypto.createHash("sha256").update(recordBuf).digest("hex");

    const commit = {
      schemaVersion: "2.0",
      assignmentId: "test-assignment-123",
      assignmentRecordSha256: recSha,
      status: "committed",
      committedAt: new Date().toISOString()
    };
    const commitBuf = Buffer.from(JSON.stringify(commit, null, 2));
    fs.writeFileSync(path.join(assignmentDir, "metadata", "commit.json"), commitBuf);
    const commitSha = crypto.createHash("sha256").update(commitBuf).digest("hex");

    const pointer = {
      schemaVersion: "2.0",
      deploymentId: "dhaka_south",
      assignmentId: "test-assignment-123",
      modelId: "ridge_regression",
      commitSha256: commitSha
    };
    fs.writeFileSync(path.join(pointerDir, "latest.json"), JSON.stringify(pointer));

    const authority = resolveActiveModel(ROOT, tmpDir, "dhaka_south");
    assert.equal(authority.authoritySource, "committed_assignment");
    assert.equal(authority.modelId, "ridge_regression");
    assert.equal(authority.assignmentId, "test-assignment-123");
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
});
