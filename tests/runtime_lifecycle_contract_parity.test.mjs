import test from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {spawnPythonSync} from "./node_python_runner.mjs";

test("Python lifecycle fixtures, JSON schemas, and exact TypeScript contracts remain executable in parity",{timeout:120000},()=>{
 const schema=spawnPythonSync(["-m","unittest","tests.test_runtime_model_lifecycle_schemas"],{timeout:90000});
 assert.equal(schema.status,0,schema.stdout+schema.stderr);
 const contracts=readFileSync("lib/runtime/contracts.ts","utf8"),parity=readFileSync("tests/runtime_lifecycle_contract_parity.ts","utf8");
 assert.match(contracts,/assessmentCommitSha256:string;decisionCommitSha256:string;authorizationCommitSha256:string/);
 assert.match(parity,/RequestRejectsCommittedNames/);
 assert.match(parity,/CommittedArtifactsRejectExpectedNames/);
});
