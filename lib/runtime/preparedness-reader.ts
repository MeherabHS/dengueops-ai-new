import "server-only";

import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import type { AvailabilityScenario } from "@/lib/community/contracts";
import { RuntimePublicError } from "./errors";
import type { VerifiedCurrentForecast } from "./dashboard-reader";
import type { VerifiedHospitalInventory } from "./hospital-inventory-reader";
import {
  assertContained,
  preparednessQualificationPaths,
  preparednessQualificationVersionPaths,
} from "./paths";

type JsonObject = Record<string, unknown>;
const SHA = /^[a-f0-9]{64}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SCENARIOS: AvailabilityScenario[] = [
  "baseline_availability",
  "constrained_availability",
  "severe_constraint",
];
const EXPECTED_ARTIFACTS = [
  "allocation_policy_snapshot.json",
  "forecast_commit_snapshot.json",
  "forecast_output_snapshot.json",
  "forecast_uncertainty_snapshot.json",
  "formula_activation_policy_snapshot.json",
  "formula_registry_snapshot.json",
  "formula_snapshot.json",
  "official_capacity_reference_snapshot.json",
  "official_hospital_inventory_snapshot.json",
  "preparedness_evidence.json",
  "synthetic_inventory_snapshot.json",
  "synthetic_scenario_policy_snapshot.json",
].sort();

const digest = (value: Buffer) => createHash("sha256").update(value).digest("hex");

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("object");
  return value as JsonObject;
}

export interface VerifiedPreparedness {
  pointer: JsonObject | null;
  pointerSha256: string | null;
  evidence: JsonObject;
  evidenceSha256: string;
  commit: JsonObject;
  commitSha256: string;
}

async function verifyVersion(
  runtimeRoot: string,
  preparednessId: string,
  forecast: VerifiedCurrentForecast,
  inventory: VerifiedHospitalInventory,
): Promise<Omit<VerifiedPreparedness, "pointer" | "pointerSha256">> {
  const version = preparednessQualificationVersionPaths(runtimeRoot, preparednessId);
  const [commitBytes, evidenceBytes] = await Promise.all([
    readFile(version.commit),
    readFile(version.evidence),
  ]);
  const commit = object(JSON.parse(commitBytes.toString("utf8")));
  const evidence = object(JSON.parse(evidenceBytes.toString("utf8")));
  const hashes = object(commit.artifactHashes);
  const names = (await readdir(version.artifacts)).sort();
  if (names.join("|") !== EXPECTED_ARTIFACTS.join("|")
    || Object.keys(hashes).sort().join("|") !== EXPECTED_ARTIFACTS.join("|")) {
    throw new Error("artifact set");
  }
  for (const name of names) {
    const artifactPath = assertContained(version.artifacts, path.join(version.artifacts, name));
    if (!SHA.test(String(hashes[name])) || digest(await readFile(artifactPath)) !== hashes[name]) {
      throw new Error("artifact hash");
    }
  }
  const forecastSource = object(evidence.forecastSource);
  if (commit.preparednessId !== preparednessId
    || evidence.preparednessId !== preparednessId
    || commit.scenarioId !== evidence.scenarioId
    || !SCENARIOS.includes(String(evidence.scenarioId) as AvailabilityScenario)
    || commit.deploymentId !== "dhaka_south"
    || evidence.deploymentId !== "dhaka_south"
    || commit.evidenceScope !== "synthetic_qualification"
    || evidence.evidenceScope !== "synthetic_qualification"
    || evidence.operationalDhakaValidation !== false
    || evidence.operationalUseAllowed !== false
    || evidence.clinicalUseAllowed !== false
    || evidence.hospitalDecisionUseAllowed !== false
    || evidence.currentHospitalAvailability !== "synthetic"
    || evidence.preparednessInterpretation !== "system_behavior_qualification_only"
    || hashes["preparedness_evidence.json"] !== digest(evidenceBytes)
    || hashes["forecast_commit_snapshot.json"] !== forecast.commitSha256
    || hashes["forecast_output_snapshot.json"] !== forecast.forecastSha256
    || hashes["official_hospital_inventory_snapshot.json"] !== inventory.inventoryRawSha256
    || commit.forecastRunId !== forecast.pointer.runId
    || commit.forecastCommitSha256 !== forecast.commitSha256
    || forecastSource.runId !== forecast.pointer.runId
    || forecastSource.forecastCommitSha256 !== forecast.commitSha256
    || forecastSource.forecastReported !== forecast.forecast.forecastReported
    || !Array.isArray(evidence.hospitals)) {
    throw new Error("package identity");
  }
  const ids = new Set<string>();
  for (const candidate of evidence.hospitals) {
    const row = object(candidate);
    const id = String(row.hospitalId);
    if (ids.has(id) || ![
      "calculated_synthetic_gap_present",
      "no_calculated_synthetic_gap",
      "insufficient_capacity_reference",
      "synthetic_inventory_unavailable",
      "formula_not_configured",
      "formula_scope_mismatch",
      "forecast_source_unavailable",
      "source_verification_failed",
      "not_eligible",
      "eligibility_not_verified",
    ].includes(String(row.status))) {
      throw new Error("hospital result");
    }
    ids.add(id);
  }
  return {
    evidence,
    evidenceSha256: digest(evidenceBytes),
    commit,
    commitSha256: digest(commitBytes),
  };
}

async function findScenarioId(
  runtimeRoot: string,
  scenario: AvailabilityScenario,
  forecast: VerifiedCurrentForecast,
  inventory: VerifiedHospitalInventory,
  currentBindings: JsonObject,
): Promise<string> {
  const authority = preparednessQualificationPaths(runtimeRoot, "dhaka_south");
  const candidates = (await readdir(authority.versions, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory() && UUID.test(entry.name))
    .map((entry) => entry.name);
  const matches: string[] = [];
  for (const id of candidates) {
    try {
      const version = preparednessQualificationVersionPaths(runtimeRoot, id);
      const evidence = object(JSON.parse(await readFile(version.evidence, "utf8")));
      if (evidence.scenarioId !== scenario) continue;
      const source = object(evidence.forecastSource);
      if (source.runId !== forecast.pointer.runId || source.forecastCommitSha256 !== forecast.commitSha256) continue;
      const bindings = object(evidence.authorityBindings);
      if (bindings.syntheticInventoryId !== currentBindings.syntheticInventoryId
        || bindings.syntheticInventorySha256 !== currentBindings.syntheticInventorySha256
        || bindings.scenarioPolicyId !== currentBindings.scenarioPolicyId
        || bindings.scenarioPolicySha256 !== currentBindings.scenarioPolicySha256
        || bindings.formulaId !== currentBindings.formulaId
        || bindings.formulaSha256 !== currentBindings.formulaSha256) continue;
      const verified = await verifyVersion(runtimeRoot, id, forecast, inventory);
      const snapshotHash = object(verified.commit.artifactHashes)["official_hospital_inventory_snapshot.json"];
      if (snapshotHash === inventory.inventoryRawSha256) matches.push(id);
    } catch {
      // A malformed or historical package cannot become current public authority.
    }
  }
  if (matches.length !== 1) throw new Error("scenario authority");
  return matches[0];
}

export async function readVerifiedPreparedness(
  runtimeRoot: string,
  scenario: AvailabilityScenario | null,
  forecast: VerifiedCurrentForecast,
  inventory: VerifiedHospitalInventory,
): Promise<VerifiedPreparedness> {
  try {
    const authority = preparednessQualificationPaths(runtimeRoot, "dhaka_south");
    const pointerBytes = await readFile(authority.latest);
    const pointer = object(JSON.parse(pointerBytes.toString("utf8")));
    if (pointer.schemaVersion !== "1.0"
      || pointer.deploymentId !== "dhaka_south"
      || pointer.evidenceScope !== "synthetic_qualification"
      || !UUID.test(String(pointer.preparednessId))
      || !SCENARIOS.includes(String(pointer.scenarioId) as AvailabilityScenario)
      || !SHA.test(String(pointer.evidenceSha256))
      || !SHA.test(String(pointer.commitSha256))) {
      throw new Error("pointer identity");
    }
    const pointerId = String(pointer.preparednessId);
    const expectedEvidencePath = `hospital-preparedness-qualification/${pointerId}/artifacts/preparedness_evidence.json`;
    const expectedCommitPath = `hospital-preparedness-qualification/${pointerId}/metadata/commit.json`;
    if (pointer.evidencePath !== expectedEvidencePath || pointer.commitPath !== expectedCommitPath) {
      throw new Error("pointer path");
    }
    const current = await verifyVersion(runtimeRoot, pointerId, forecast, inventory);
    if (current.evidenceSha256 !== pointer.evidenceSha256
      || current.commitSha256 !== pointer.commitSha256
      || current.evidence.scenarioId !== pointer.scenarioId) {
      throw new Error("pointer binding");
    }
    const selectedId = scenario
      ? await findScenarioId(runtimeRoot, scenario, forecast, inventory, object(current.evidence.authorityBindings))
      : pointerId;
    const verified = selectedId === pointerId
      ? current
      : await verifyVersion(runtimeRoot, selectedId, forecast, inventory);
    return {
      pointer: scenario ? null : pointer,
      pointerSha256: scenario ? null : digest(pointerBytes),
      ...verified,
    };
  } catch {
    throw new RuntimePublicError(
      "preparedness_integrity_failure",
      "storage",
      "The current preparedness qualification evidence failed verification.",
      503,
      true,
    );
  }
}
