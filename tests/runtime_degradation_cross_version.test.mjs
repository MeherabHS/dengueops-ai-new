import test from "node:test";
import assert from "node:assert/strict";
import {execFileSync} from "node:child_process";
import {mkdtemp, mkdir, readFile, rm, writeFile} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import {fileURLToPath} from "node:url";
import {findPython} from "./node_python_runner.mjs";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("current degradation reads use the p2-v3 pointer without redefining historical paths", async () => {
  const paths = await read("lib/runtime/paths.ts");
  const store = await read("lib/runtime/model-degradation-store.ts");
  assert.match(paths, /currentModelDegradationLatestPaths/);
  assert.match(paths, /latest_p2-v3\.json/);
  assert.match(paths, /modelDegradationLatestPaths[\s\S]*latest\.json/);
  assert.match(store, /readVerifiedCurrentModelDegradationEvidence/);
  assert.match(store, /readVerifiedModelDegradationEvidenceById/);
  assert.match(store, /currentModelDegradationLatestPaths/);
  assert.doesNotMatch(
    store.slice(store.indexOf("async function verifyBundle"), store.indexOf("export async function readVerifiedModelDegradationEvidenceById")),
    /monitoringPaths|monitoring\/latest\.json/,
  );
});

test("historical snapshots are bound through commit, summary, and included outcomes", async () => {
  const store = await read("lib/runtime/model-degradation-store.ts");
  for (const token of [
    "monitoringLatestSnapshotSha256",
    "monitoringSummarySha256",
    "includedOutcomeSetSha256",
    "readVerifiedForecastOutcome",
  ]) {
    assert.match(store, new RegExp(token));
  }
  assert.match(store, /const previous=.*p2-v2/);
  assert.match(store, /const current=.*p2-v3/);
  assert.match(store, /policyVersion!==["']p2-v1["']/);
});

test("default read returns D2 while explicit D1 survives M2 and assignment-pointer change", {timeout: 180_000}, async () => {
  const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const base = await mkdtemp(path.join(os.tmpdir(), "dengueops-b8-node-"));
  try {
    const python = findPython().command;
    const script = [
      "import json,sys",
      "from pathlib import Path",
      "sys.path.insert(0,str(Path.cwd()/'analytics'))",
      "from tests.test_runtime_model_degradation_cross_version import build_cross_version_runtime",
      `b=build_cross_version_runtime(Path(${JSON.stringify(base)}))`,
      "print(json.dumps({'runtime':str(b['runtime']),'d1':b['d1']['commit']['evidenceId'],'d2':b['d2']['commit']['evidenceId']}))",
    ].join(";");
    const output = execFileSync(python, ["-c", script], {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {...process.env, PYTHONDONTWRITEBYTECODE: "1"},
      maxBuffer: 10 * 1024 * 1024,
    });
    const fixture = JSON.parse(output.trim().split(/\r?\n/).at(-1));
    const store = await import("../lib/runtime/model-degradation-store.ts");
    const current = await store.readVerifiedCurrentModelDegradationEvidence(repositoryRoot, fixture.runtime, "dhaka_south");
    const historical = await store.readVerifiedModelDegradationEvidenceById(repositoryRoot, fixture.runtime, "dhaka_south", fixture.d1);
    assert.equal(current.evidence.evidenceId, fixture.d2);
    assert.equal(historical.evidence.evidenceId, fixture.d1);

    const assignment = path.join(fixture.runtime, "deployments", "dhaka_south", "model-assignment");
    await mkdir(assignment, {recursive: true});
    await writeFile(path.join(assignment, "latest.json"), '{"changed":true}\n');
    const reread = await store.readVerifiedModelDegradationEvidenceById(repositoryRoot, fixture.runtime, "dhaka_south", fixture.d1);
    assert.equal(reread.evidence.evidenceId, fixture.d1);

    const d1Root = path.join(fixture.runtime, "degradation-evidence", fixture.d1);
    const d1Commit = JSON.parse(await readFile(path.join(d1Root, "metadata", "commit.json"), "utf8"));
    const tamperCases = [
      path.join(d1Root, "artifacts", "monitoring_latest_snapshot.json"),
      path.join(fixture.runtime, d1Commit.monitoringSummaryPath),
      path.join(fixture.runtime, "forecast-outcomes", d1Commit.includedOutcomes[0].outcomeId, "metadata", "commit.json"),
      path.join(fixture.runtime, "forecast-outcomes", d1Commit.includedOutcomes[0].outcomeId, "artifacts", "outcome_evaluation.json"),
    ];
    for (const target of tamperCases) {
      const original = await readFile(target);
      try {
        await writeFile(target, Buffer.concat([original, Buffer.from(" ")]));
        await assert.rejects(
          store.readVerifiedModelDegradationEvidenceById(repositoryRoot, fixture.runtime, "dhaka_south", fixture.d1),
          error => error?.code === "model_degradation_integrity_error",
        );
      } finally {
        await writeFile(target, original);
      }
    }

    const latest = path.join(fixture.runtime, "deployments", "dhaka_south", "degradation", "latest_p2-v3.json");
    const latestBytes = await readFile(latest);
    try {
      const changed = JSON.parse(latestBytes.toString("utf8"));
      changed.commitSha256 = "0".repeat(64);
      await writeFile(latest, JSON.stringify(changed));
      await assert.rejects(
        store.readVerifiedCurrentModelDegradationEvidence(repositoryRoot, fixture.runtime, "dhaka_south"),
        error => error?.code === "model_degradation_integrity_error",
      );
    } finally {
      await writeFile(latest, latestBytes);
    }
  } finally {
    await rm(base, {recursive: true, force: true});
  }
});

test("explicit historical p2-v1 evidence remains readable through its frozen contract", {timeout: 180_000}, async () => {
  const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const base = await mkdtemp(path.join(os.tmpdir(), "dengueops-b8-p1-node-"));
  try {
    const python = findPython().command;
    const script = [
      "import json,sys",
      "from pathlib import Path",
      "sys.path.insert(0,str(Path.cwd()/'analytics'))",
      "from tests.lifecycle_fixtures import build_promotion_chain_p2_v1",
      `b=build_promotion_chain_p2_v1(Path(${JSON.stringify(base)}),Path.cwd())`,
      "p=json.loads((b['runtime']/'deployments/dhaka_south/degradation/latest.json').read_text())",
      "print(json.dumps({'runtime':str(b['runtime']),'evidenceId':p['evidenceId']}))",
    ].join(";");
    const output = execFileSync(python, ["-c", script], {
      cwd: repositoryRoot,
      encoding: "utf8",
      env: {...process.env, PYTHONDONTWRITEBYTECODE: "1"},
      maxBuffer: 10 * 1024 * 1024,
    });
    const fixture = JSON.parse(output.trim().split(/\r?\n/).at(-1));
    const store = await import("../lib/runtime/model-degradation-store.ts");
    const historical = await store.readVerifiedModelDegradationEvidenceById(repositoryRoot, fixture.runtime, "dhaka_south", fixture.evidenceId);
    assert.equal(historical.evidence.schemaVersion, "1.0");
    assert.equal(historical.commit.policyVersion, "p2-v1");
  } finally {
    await rm(base, {recursive: true, force: true});
  }
});
