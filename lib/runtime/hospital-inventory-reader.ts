import "server-only";

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { RuntimePublicError } from "./errors";
import {
  assertContained,
  hospitalInventoryAuthorityPaths,
  hospitalInventoryVersionPaths,
} from "./paths";

type JsonObject = Record<string, unknown>;
const SHA = /^[a-f0-9]{64}$/;
const SAFE_ID = /^[a-z0-9][a-z0-9_-]{0,127}$/;
const sha = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");

const canonical = (value: unknown): string => Array.isArray(value)
  ? `[${value.map(canonical).join(",")}]`
  : value && typeof value === "object"
    ? `{${Object.entries(value as JsonObject).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`
    : JSON.stringify(value);

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new RuntimePublicError("inventory_tampered", "storage", "The hospital inventory failed verification.", 503, true);
  }
  return value as JsonObject;
}

function exactKeys(value: JsonObject, fields: string[]): boolean {
  return Object.keys(value).sort().join("|") === [...fields].sort().join("|");
}

function validateInventory(value: unknown): JsonObject {
  const inventory = object(value);
  const common = ["schemaVersion", "inventoryId", "inventoryVersion", "deploymentId", "deploymentDisplayName", "changeReason", "createdAt", "operatorIdentifier", "verificationStatus", "stalenessThresholdStatus", "allocationStatus", "sourceReferences", "hospitals"];
  const current = String(inventory.inventoryVersion).startsWith("3.");
  const expected = current ? [...common, "capacityReferenceId", "capacityReferenceSha256"] : common;
  if (!exactKeys(inventory, expected)
    || inventory.schemaVersion !== "1.0"
    || inventory.deploymentId !== "dhaka_south"
    || inventory.deploymentDisplayName !== "Dhaka"
    || inventory.stalenessThresholdStatus !== "not_governed"
    || inventory.allocationStatus !== "not_configured"
    || !SAFE_ID.test(String(inventory.inventoryId))
    || !Array.isArray(inventory.sourceReferences)
    || !Array.isArray(inventory.hospitals)
    || (current && !SHA.test(String(inventory.capacityReferenceSha256)))) {
    throw new RuntimePublicError("inventory_tampered", "storage", "The hospital inventory failed verification.", 503, true);
  }
  const references = new Set<string>();
  for (const candidate of inventory.sourceReferences) {
    const reference = object(candidate);
    const referenceId = String(reference.verificationReferenceId);
    if (!SAFE_ID.test(referenceId)
      || references.has(referenceId)
      || typeof reference.sourceUrl !== "string"
      || !reference.sourceUrl.startsWith("https://")
      || !Array.isArray(reference.supportedFields)) {
      throw new RuntimePublicError("inventory_tampered", "storage", "A source reference failed verification.", 503, true);
    }
    references.add(referenceId);
  }
  const ids = new Set<string>();
  const names = new Set<string>();
  for (const candidate of inventory.hospitals) {
    const hospital = object(candidate);
    const id = String(hospital.hospitalId);
    const name = String(hospital.officialName).normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase("en");
    const identity = object(hospital.identityVerification);
    const allocation = object(hospital.allocationShare);
    if (!SAFE_ID.test(id)
      || ids.has(id)
      || (hospital.active === true && names.has(name))
      || !["public_government", "government_autonomous"].includes(String(hospital.ownership))
      || !references.has(String(identity.verificationReferenceId))
      || identity.status !== "verified"
      || allocation.status !== "not_configured"
      || allocation.value !== null
      || !Array.isArray(hospital.resources)) {
      throw new RuntimePublicError("inventory_tampered", "storage", "A hospital record failed verification.", 503, true);
    }
    if (current && (!["included", "not_included"].includes(String(hospital.participationStatus))
      || !["pending_review", "not_applicable"].includes(String(hospital.managementDecisionStatus))
      || (hospital.selectedBedCapacity !== null && (!Number.isSafeInteger(hospital.selectedBedCapacity) || Number(hospital.selectedBedCapacity) < 0))
      || hospital.currentAvailableBeds !== null)) {
      throw new RuntimePublicError("inventory_tampered", "storage", "A current hospital record failed verification.", 503, true);
    }
    ids.add(id);
    if (hospital.active === true) names.add(name);
    for (const resourceCandidate of hospital.resources) {
      const resource = object(resourceCandidate);
      if (!["verified_capacity_reference", "verified", "reported", "unknown", "unavailable"].includes(String(resource.dataStatus))
        || (resource.quantity !== null && (!Number.isSafeInteger(resource.quantity) || Number(resource.quantity) < 0))
        || (["unknown", "unavailable"].includes(String(resource.dataStatus)) && resource.quantity !== null)
        || !references.has(String(resource.verificationReferenceId))) {
        throw new RuntimePublicError("inventory_tampered", "storage", "A resource record failed verification.", 503, true);
      }
    }
  }
  return inventory;
}

export interface VerifiedHospitalInventory {
  pointer: JsonObject;
  pointerSha256: string;
  inventory: JsonObject;
  inventoryRawSha256: string;
  inventoryCanonicalSha256: string;
  commit: JsonObject;
  commitSha256: string;
}

export async function readVerifiedHospitalInventoryById(
  runtimeRoot: string,
  inventoryId: string,
): Promise<Omit<VerifiedHospitalInventory, "pointer" | "pointerSha256">> {
  const version = hospitalInventoryVersionPaths(runtimeRoot, inventoryId);
  try {
    const [artifactBytes, commitBytes, sourceBytes] = await Promise.all([
      readFile(version.artifact),
      readFile(version.commit),
      readFile(version.sourceReferences),
    ]);
    const inventory = validateInventory(JSON.parse(artifactBytes.toString("utf8")));
    const commit = object(JSON.parse(commitBytes.toString("utf8")));
    const sourceSnapshot = object(JSON.parse(sourceBytes.toString("utf8")));
    const expectedArtifactPath = `hospital-inventories/${inventoryId}/artifacts/hospital_inventory.json`;
    const expectedSourcePath = `hospital-inventories/${inventoryId}/metadata/source_references.json`;
    if (commit.inventoryId !== inventoryId
      || commit.inventoryVersion !== inventory.inventoryVersion
      || commit.deploymentId !== inventory.deploymentId
      || commit.inventoryRawSha256 !== sha(artifactBytes)
      || commit.inventoryCanonicalSha256 !== sha(canonical(inventory))
      || commit.inventoryArtifactPath !== expectedArtifactPath
      || commit.sourceReferencesPath !== expectedSourcePath
      || commit.sourceReferencesSha256 !== sha(sourceBytes)
      || sourceSnapshot.schemaVersion !== "1.0"
      || sourceSnapshot.inventoryId !== inventoryId
      || canonical(sourceSnapshot.sourceReferences) !== canonical(inventory.sourceReferences)) {
      throw new Error("inventory commit identity");
    }
    return {
      inventory,
      inventoryRawSha256: sha(artifactBytes),
      inventoryCanonicalSha256: sha(canonical(inventory)),
      commit,
      commitSha256: sha(commitBytes),
    };
  } catch (error) {
    if (error instanceof RuntimePublicError) throw error;
    throw new RuntimePublicError("inventory_integrity_failure", "storage", "The hospital inventory authority failed verification.", 503, true);
  }
}

export async function readVerifiedCurrentHospitalInventory(
  runtimeRoot: string,
  deploymentId: string,
): Promise<VerifiedHospitalInventory> {
  const authority = hospitalInventoryAuthorityPaths(runtimeRoot, deploymentId);
  try {
    const pointerBytes = await readFile(authority.latest);
    const pointer = object(JSON.parse(pointerBytes.toString("utf8")));
    if (pointer.schemaVersion !== "1.0"
      || pointer.deploymentId !== deploymentId
      || pointer.deploymentDisplayName !== "Dhaka"
      || !SAFE_ID.test(String(pointer.inventoryId))
      || !UUID.test(String(pointer.activationId))
      || !SHA.test(String(pointer.inventoryArtifactSha256))
      || !SHA.test(String(pointer.inventoryCommitSha256))
      || !SHA.test(String(pointer.activationRecordSha256))) {
      throw new Error("inventory pointer identity");
    }
    const inventoryId = String(pointer.inventoryId);
    const verified = await readVerifiedHospitalInventoryById(runtimeRoot, inventoryId);
    const expectedArtifact = `hospital-inventories/${inventoryId}/artifacts/hospital_inventory.json`;
    const expectedCommit = `hospital-inventories/${inventoryId}/metadata/commit.json`;
    const expectedActivation = `deployments/${deploymentId}/hospital-inventory/activations/${pointer.activationId}.json`;
    if (pointer.inventoryArtifactPath !== expectedArtifact
      || pointer.inventoryCommitPath !== expectedCommit
      || pointer.activationRecordPath !== expectedActivation
      || pointer.inventoryArtifactSha256 !== verified.inventoryRawSha256
      || pointer.inventoryCommitSha256 !== verified.commitSha256) {
      throw new Error("inventory pointer binding");
    }
    const activationPath = assertContained(runtimeRoot, path.join(runtimeRoot, expectedActivation));
    const activationBytes = await readFile(activationPath);
    const activation = object(JSON.parse(activationBytes.toString("utf8")));
    if (sha(activationBytes) !== pointer.activationRecordSha256
      || activation.activationId !== pointer.activationId
      || activation.inventoryId !== inventoryId
      || activation.inventoryArtifactSha256 !== verified.inventoryRawSha256
      || activation.inventoryCommitSha256 !== verified.commitSha256
      || activation.previousPointerSha256 !== pointer.previousPointerSha256
      || activation.previousInventoryId !== pointer.previousInventoryId
      || activation.activationOperator !== pointer.activationOperator
      || activation.activationReason !== pointer.activationReason
      || activation.activatedAt !== pointer.activatedAt) {
      throw new Error("inventory activation binding");
    }
    return { pointer, pointerSha256: sha(pointerBytes), ...verified };
  } catch (error) {
    if (error instanceof RuntimePublicError) throw error;
    throw new RuntimePublicError("current_inventory_integrity_failure", "storage", "The current hospital inventory failed verification.", 503, true);
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
