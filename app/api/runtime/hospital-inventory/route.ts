import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type { HospitalInventoryReadResponse } from "@/lib/runtime/contracts";
import { loadDeploymentProductScope } from "@/lib/runtime/deployment-scope";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import {
  assertContained,
  hospitalInventoryAuthorityPaths,
  hospitalInventoryVersionPaths,
} from "@/lib/runtime/paths";

export const runtime = "nodejs";

const sha = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");
const canonical = (value: unknown): string => Array.isArray(value)
  ? `[${value.map(canonical).join(",")}]`
  : value && typeof value === "object"
    ? `{${Object.entries(value as Record<string, unknown>).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`
    : JSON.stringify(value);
const exactKeys = (value: Record<string, unknown>, expected: string[]) =>
  Object.keys(value).sort().join("|") === [...expected].sort().join("|");

function validateInventory(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new RuntimePublicError("inventory_tampered", "storage", "The hospital inventory failed verification.", 409);
  const inventory = value as Record<string, unknown>;
  const rootFields = ["schemaVersion", "inventoryId", "inventoryVersion", "deploymentId", "deploymentDisplayName", "changeReason", "createdAt", "operatorIdentifier", "verificationStatus", "stalenessThresholdStatus", "allocationStatus", "sourceReferences", "hospitals"];
  if (!exactKeys(inventory, rootFields) || inventory.schemaVersion !== "1.0" || inventory.deploymentId !== "dhaka_south"
    || inventory.deploymentDisplayName !== "Dhaka" || inventory.stalenessThresholdStatus !== "not_governed"
    || inventory.allocationStatus !== "not_configured" || !Array.isArray(inventory.sourceReferences) || !Array.isArray(inventory.hospitals)) {
    throw new RuntimePublicError("inventory_tampered", "storage", "The hospital inventory failed verification.", 409);
  }
  const sourceFields = ["verificationReferenceId", "sourceOrganization", "sourceUrl", "retrievedAt", "verifiedAt", "supportedFields"];
  const references = new Set<string>();
  for (const candidateReference of inventory.sourceReferences as unknown[]) {
    if (!candidateReference || typeof candidateReference !== "object" || Array.isArray(candidateReference)) throw new RuntimePublicError("inventory_tampered", "storage", "A source reference failed verification.", 409);
    const reference = candidateReference as Record<string, unknown>, referenceId = String(reference.verificationReferenceId);
    if (!exactKeys(reference, sourceFields) || !/^[a-z0-9][a-z0-9_-]{0,127}$/.test(referenceId) || references.has(referenceId)
      || typeof reference.sourceUrl !== "string" || !reference.sourceUrl.startsWith("https://") || !Array.isArray(reference.supportedFields)) {
      throw new RuntimePublicError("inventory_tampered", "storage", "A source reference failed verification.", 409);
    }
    references.add(referenceId);
  }
  const hospitalIds = new Set<string>(), activeNames = new Set<string>();
  for (const candidate of inventory.hospitals as unknown[]) {
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) throw new RuntimePublicError("inventory_tampered", "storage", "A hospital record failed verification.", 409);
    const hospital = candidate as Record<string, unknown>, hospitalId = String(hospital.hospitalId), name = String(hospital.officialName).normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase("en");
    const identity = hospital.identityVerification as Record<string, unknown>;
    if (!/^[a-z0-9][a-z0-9_-]{0,127}$/.test(hospitalId) || hospitalIds.has(hospitalId) || (hospital.active === true && activeNames.has(name))
      || hospital.ownership !== "public_government" || !Array.isArray(hospital.resources)
      || !identity || identity.status !== "verified" || !references.has(String(identity.verificationReferenceId))
      || !hospital.allocationShare || (hospital.allocationShare as Record<string, unknown>).status !== "not_configured"
      || (hospital.allocationShare as Record<string, unknown>).value !== null) {
      throw new RuntimePublicError("inventory_tampered", "storage", "A hospital record failed verification.", 409);
    }
    hospitalIds.add(hospitalId); if (hospital.active === true) activeNames.add(name);
    for (const candidateResource of hospital.resources as unknown[]) {
      const resource = candidateResource as Record<string, unknown>;
      if (!resource || !exactKeys(resource, ["resourceType", "unit", "quantity", "dataStatus", "asOf", "verificationReferenceId"])
        || !["verified", "reported", "unknown", "unavailable"].includes(String(resource.dataStatus))
        || (resource.quantity === null) !== ["unknown", "unavailable"].includes(String(resource.dataStatus))
        || !references.has(String(resource.verificationReferenceId))) {
        throw new RuntimePublicError("inventory_tampered", "storage", "A resource record failed verification.", 409);
      }
    }
  }
  return inventory;
}

async function readActive(config: ReturnType<typeof loadRuntimeConfig>, scope: Awaited<ReturnType<typeof loadDeploymentProductScope>>) {
  const authority = hospitalInventoryAuthorityPaths(config.runtimeRoot, scope.internalDeploymentId);
  try {
    const pointerBytes = await readFile(authority.latest);
    const pointer = JSON.parse(pointerBytes.toString("utf8")) as Record<string, unknown>;
    const pointerFields = ["schemaVersion", "deploymentId", "deploymentDisplayName", "inventoryId", "inventoryArtifactPath", "inventoryArtifactSha256", "inventoryCommitPath", "inventoryCommitSha256", "activationId", "activationRecordPath", "activationRecordSha256", "previousPointerSha256", "previousInventoryId", "activationOperator", "activationReason", "activatedAt"];
    if (!exactKeys(pointer, pointerFields) || pointer.schemaVersion !== "1.0" || pointer.deploymentId !== scope.internalDeploymentId || pointer.deploymentDisplayName !== scope.deploymentDisplayName
      || typeof pointer.inventoryId !== "string" || !/^[a-z0-9][a-z0-9_-]{0,127}$/.test(pointer.inventoryId)) {
      throw new RuntimePublicError("inventory_pointer_tampered", "storage", "The active inventory pointer failed verification.", 409);
    }
    const version = hospitalInventoryVersionPaths(config.runtimeRoot, pointer.inventoryId);
    const expectedArtifact = `hospital-inventories/${pointer.inventoryId}/artifacts/hospital_inventory.json`;
    const expectedCommit = `hospital-inventories/${pointer.inventoryId}/metadata/commit.json`;
    if (pointer.inventoryArtifactPath !== expectedArtifact || pointer.inventoryCommitPath !== expectedCommit) throw new RuntimePublicError("inventory_pointer_tampered", "storage", "The active inventory pointer failed verification.", 409);
    const expectedActivation = `deployments/dhaka_south/hospital-inventory/activations/${pointer.activationId}.json`;
    if (pointer.activationRecordPath !== expectedActivation) throw new RuntimePublicError("inventory_pointer_tampered", "storage", "The active inventory activation path failed verification.", 409);
    const activationPath = assertContained(config.runtimeRoot, path.join(config.runtimeRoot, expectedActivation));
    const [artifactBytes, commitBytes, activationBytes, referenceBytes] = await Promise.all([readFile(version.artifact), readFile(version.commit), readFile(activationPath), readFile(version.sourceReferences)]);
    if (sha(artifactBytes) !== pointer.inventoryArtifactSha256 || sha(commitBytes) !== pointer.inventoryCommitSha256 || sha(activationBytes) !== pointer.activationRecordSha256) {
      throw new RuntimePublicError("inventory_pointer_tampered", "storage", "The active inventory pointer hash failed verification.", 409);
    }
    const inventory = validateInventory(JSON.parse(artifactBytes.toString("utf8")));
    const commit = JSON.parse(commitBytes.toString("utf8")) as Record<string, unknown>;
    const commitFields = ["schemaVersion", "inventoryId", "inventoryVersion", "deploymentId", "deploymentDisplayName", "inventoryCanonicalSha256", "inventoryRawSha256", "inventoryArtifactPath", "sourceReferencesSha256", "sourceReferencesPath", "operatorIdentifier", "changeReason", "verificationStatus", "publishedAt"];
    const expectedReferences = `hospital-inventories/${pointer.inventoryId}/metadata/source_references.json`;
    if (!exactKeys(commit, commitFields) || commit.inventoryId !== pointer.inventoryId || commit.inventoryRawSha256 !== sha(artifactBytes)
      || commit.inventoryCanonicalSha256 !== sha(canonical(inventory)) || commit.inventoryArtifactPath !== expectedArtifact
      || commit.sourceReferencesPath !== expectedReferences || commit.sourceReferencesSha256 !== sha(referenceBytes)) {
      throw new RuntimePublicError("inventory_commit_tampered", "storage", "The hospital inventory commit failed verification.", 409);
    }
    const referenceSnapshot = JSON.parse(referenceBytes.toString("utf8")) as Record<string, unknown>;
    if (!exactKeys(referenceSnapshot, ["schemaVersion", "inventoryId", "sourceReferences"]) || referenceSnapshot.schemaVersion !== "1.0"
      || referenceSnapshot.inventoryId !== pointer.inventoryId || canonical(referenceSnapshot.sourceReferences) !== canonical(inventory.sourceReferences)) {
      throw new RuntimePublicError("inventory_commit_tampered", "storage", "The inventory source-reference snapshot failed verification.", 409);
    }
    const activation = JSON.parse(activationBytes.toString("utf8")) as Record<string, unknown>;
    const activationFields = ["schemaVersion", "activationId", "deploymentId", "inventoryId", "inventoryArtifactSha256", "inventoryCommitSha256", "previousPointerSha256", "previousInventoryId", "activationOperator", "activationReason", "activatedAt"];
    if (!exactKeys(activation, activationFields) || activation.activationId !== pointer.activationId || activation.inventoryId !== pointer.inventoryId
      || activation.inventoryArtifactSha256 !== pointer.inventoryArtifactSha256 || activation.inventoryCommitSha256 !== pointer.inventoryCommitSha256
      || activation.previousPointerSha256 !== pointer.previousPointerSha256 || activation.previousInventoryId !== pointer.previousInventoryId
      || activation.activationOperator !== pointer.activationOperator || activation.activationReason !== pointer.activationReason || activation.activatedAt !== pointer.activatedAt) {
      throw new RuntimePublicError("inventory_pointer_tampered", "storage", "The inventory activation record failed verification.", 409);
    }
    return { status: "active" as const, inventory, canonicalSha: String(commit.inventoryCanonicalSha256), rawSha: sha(artifactBytes), commitSha: sha(commitBytes) };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    const seedPath = path.join(config.repositoryRoot, "config", "deployments", scope.internalDeploymentId, "hospital_inventory.json");
    const seedBytes = await readFile(seedPath);
    const inventory = validateInventory(JSON.parse(seedBytes.toString("utf8")));
    return { status: "not_configured" as const, inventory, canonicalSha: sha(canonical(inventory)), rawSha: sha(seedBytes), commitSha: null };
  }
}

export async function GET(): Promise<Response> {
  try {
    const config = loadRuntimeConfig(false);
    const scope = await loadDeploymentProductScope(config.repositoryRoot, config.defaultDeploymentId);
    const verified = await readActive(config, scope);
    const response: HospitalInventoryReadResponse = {
      ok: true,
      internalDeploymentId: scope.internalDeploymentId,
      deploymentDisplayName: scope.deploymentDisplayName,
      forecastDataCoverage: scope.forecastDataCoverage,
      evidenceScope: scope.evidenceScope,
      operationalDhakaValidation: scope.operationalDhakaValidation,
      activeInventoryStatus: verified.status,
      inventory: verified.inventory,
      integrity: {
        inventoryCanonicalSha256: verified.canonicalSha,
        inventoryRawSha256: verified.rawSha,
        inventoryCommitSha256: verified.commitSha,
      },
    };
    return Response.json(response, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error);
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  }
}
