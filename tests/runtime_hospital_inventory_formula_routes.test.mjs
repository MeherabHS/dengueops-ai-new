import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = path => readFile(new URL(`../${path}`, import.meta.url), "utf8");

test("hospital inventory route is read-only and verifies immutable hashes", async () => {
  const route = await read("app/api/runtime/hospital-inventory/route.ts");
  assert.match(route, /export async function GET/);
  assert.doesNotMatch(route, /export async function (?:POST|PUT|PATCH|DELETE)/);
  for (const marker of ["inventoryArtifactSha256", "inventoryCommitSha256", "activationRecordSha256", "inventoryCanonicalSha256", "validateInventory"]) {
    assert.match(route, new RegExp(marker));
  }
  assert.match(route, /activeInventoryStatus/);
  assert.match(route, /quantity === null/);
  assert.match(route, /Cache-Control/);
});

test("formula route is read-only and verifies configured operational slot", async () => {
  const route = await read("app/api/runtime/formulas/route.ts");
  assert.match(route, /export async function GET/);
  assert.doesNotMatch(route, /export async function (?:POST|PUT|PATCH|DELETE)/);
  assert.match(route, /RUNTIME\.FORMULA\.ACTIVATION/);
  assert.match(route, /inventory\.gap/);
  assert.match(route, /configured/);
  assert.match(route, /activeFormulaSha256/);
  assert.match(route, /formula_registry_tampered/);
  assert.match(route, /formula_policy_tampered/);
});

test("routes expose display and internal scope separately without stack traces", async () => {
  const combined = `${await read("app/api/runtime/hospital-inventory/route.ts")}\n${await read("app/api/runtime/formulas/route.ts")}`;
  assert.match(combined, /internalDeploymentId/);
  assert.match(combined, /deploymentDisplayName/);
  assert.match(combined, /operationalDhakaValidation/);
  assert.doesNotMatch(combined, /error\.stack|stack:/);
});
