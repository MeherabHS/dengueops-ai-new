import "server-only";

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { resolveActiveModelP2V2 } from "./active-model";
import type { loadRuntimeConfig } from "./config";
import { readVerifiedAssessment, readVerifiedDecision } from "./decision-store";
import { RuntimePublicError } from "./errors";
import { assessmentPaths, assertContained, workspacePaths } from "./paths";
import { validateStrictJsonSchema } from "./strict-json-schema";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const sha256 = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");

type RuntimeConfig = ReturnType<typeof loadRuntimeConfig>;

async function strictJson(filePath: string, schemaPath: string) {
  const [bytes, schemaBytes] = await Promise.all([readFile(filePath), readFile(schemaPath)]);
  const value = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
  validateStrictJsonSchema(JSON.parse(schemaBytes.toString("utf8")), value);
  return { bytes, value };
}

function deterministicWorkspaceId(snapshotSha256: string): string {
  const value = snapshotSha256.slice(0, 32).split("");
  value[12] = "4";
  value[16] = "8";
  const compact = value.join("");
  return `${compact.slice(0, 8)}-${compact.slice(8, 12)}-${compact.slice(12, 16)}-${compact.slice(16, 20)}-${compact.slice(20)}`;
}

export interface VerifiedAssessmentDatasetSource {
  assessmentId: string;
  assessmentWorkspaceId: string;
  assessmentCommitSha256: string;
  assignmentId: string;
  assignmentPointerSha256: string;
  dengue: { bytes: Buffer; sha256: string; originalName: "verified-assessment-dengue.csv" };
  climate: { bytes: Buffer; sha256: string; originalName: "verified-assessment-climate.csv" };
  sourceSnapshotSha256: string;
  operationalWorkspaceId: string;
}

export async function resolveCurrentAssessmentDataset(config: RuntimeConfig): Promise<VerifiedAssessmentDatasetSource> {
  const active = await resolveActiveModelP2V2({
    repositoryRoot: config.repositoryRoot,
    runtimeRoot: config.runtimeRoot,
    deploymentId: config.defaultDeploymentId,
  });
  if (active.authoritySource !== "committed_assignment" || !UUID.test(active.assignmentId) || !SHA.test(active.authoritySnapshotSha256)) {
    throw new RuntimePublicError("assessment_dataset_source_unavailable", "storage", "Source assessment unavailable for the current assignment.", 409);
  }

  const assignmentRoot = assertContained(config.runtimeRoot, path.join(config.runtimeRoot, "model-assignments", active.assignmentId));
  const assignmentRecordPath = assertContained(assignmentRoot, path.join(assignmentRoot, "artifacts", "assignment_record.json"));
  const assignmentCommitPath = assertContained(assignmentRoot, path.join(assignmentRoot, "metadata", "commit.json"));
  const assignmentSchema = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "runtime_model_assignment.schema.json"));
  const assignmentCommitSchema = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "runtime_model_assignment_commit.schema.json"));
  let assignmentRecord: Awaited<ReturnType<typeof strictJson>>;
  let assignmentCommit: Awaited<ReturnType<typeof strictJson>>;
  try {
    [assignmentRecord, assignmentCommit] = await Promise.all([
      strictJson(assignmentRecordPath, assignmentSchema),
      strictJson(assignmentCommitPath, assignmentCommitSchema),
    ]);
  } catch {
    throw new RuntimePublicError("assessment_dataset_integrity_failed", "storage", "Dataset integrity verification failed for the current assignment.", 409);
  }
  const record = assignmentRecord.value;
  const commit = assignmentCommit.value;
  const assessmentId = String(record.sourceAssessmentId ?? "");
  const decisionId = String(record.sourceDecisionId ?? "");
  if (
    record.schemaVersion !== "2.0"
    || record.assignmentId !== active.assignmentId
    || record.modelId !== active.modelId
    || record.candidateRegistrySha256 !== active.candidateRegistrySha256
    || record.featureOrderSha256 !== active.featureOrderSha256
    || commit.schemaVersion !== "2.0"
    || commit.assignmentId !== active.assignmentId
    || commit.assignmentRecordSha256 !== sha256(assignmentRecord.bytes)
    || sha256(assignmentCommit.bytes) !== active.assignmentCommitSha256
    || !UUID.test(assessmentId)
    || !UUID.test(decisionId)
  ) {
    throw new RuntimePublicError("assessment_dataset_incompatible", "validation", "Dataset incompatible with the current assignment.", 409);
  }

  const decision = await readVerifiedDecision(config, decisionId).catch(() => {
    throw new RuntimePublicError("assessment_dataset_integrity_failed", "storage", "Dataset integrity verification failed for the assignment decision.", 409);
  });
  const assessmentRoot = assessmentPaths(config.runtimeRoot, assessmentId).committed;
  const inputManifestPath = assertContained(assessmentRoot, path.join(assessmentRoot, "artifacts", "input_manifest.json"));
  let verifiedAssessment: Awaited<ReturnType<typeof readVerifiedAssessment>>;
  let inputManifestBytes: Buffer;
  try {
    [verifiedAssessment, inputManifestBytes] = await Promise.all([
      readVerifiedAssessment(config, assessmentId),
      readFile(inputManifestPath),
    ]);
  } catch {
    throw new RuntimePublicError("assessment_dataset_source_unavailable", "storage", "Source assessment unavailable for the current assignment.", 409);
  }
  const assessment = verifiedAssessment.commit;
  const manifest = JSON.parse(inputManifestBytes.toString("utf8")) as Record<string, unknown>;
  const canonical = manifest.canonicalHashes as Record<string, unknown> | undefined;
  const assessmentWorkspaceId = String(assessment.workspaceId ?? "");
  const assessmentCommitSha256 = verifiedAssessment.commitSha256;
  if (
    decision.decision.assessmentId !== assessmentId
    || decision.decision.selectedModelId !== active.modelId
    || decision.decision.assessmentCommitSha256 !== assessmentCommitSha256
    || assessment.assessmentId !== assessmentId
    || assessment.deploymentId !== active.deploymentId
    || assessment.workflowMode !== "assess_dataset"
    || assessment.status !== "committed"
    || assessment.candidateRegistrySha256 !== active.candidateRegistrySha256
    || assessment.artifactHashes == null
    || (assessment.artifactHashes as Record<string, unknown>)["input_manifest.json"] !== sha256(inputManifestBytes)
    || manifest.assessmentId !== assessmentId
    || manifest.workspaceId !== assessmentWorkspaceId
    || manifest.datasetId !== assessment.datasetId
    || manifest.featureOrderSha256 !== active.featureOrderSha256
    || !UUID.test(assessmentWorkspaceId)
    || !SHA.test(String(canonical?.dengueSha256 ?? ""))
    || !SHA.test(String(canonical?.climateSha256 ?? ""))
  ) {
    throw new RuntimePublicError("assessment_dataset_incompatible", "validation", "Dataset incompatible with the current assignment.", 409);
  }

  const sourcePaths = workspacePaths(config.runtimeRoot, assessmentWorkspaceId);
  let dengueBytes: Buffer;
  let climateBytes: Buffer;
  let sourceValidationBytes: Buffer;
  try {
    [dengueBytes, climateBytes, sourceValidationBytes] = await Promise.all([
      readFile(sourcePaths.dengueCanonical),
      readFile(sourcePaths.climateCanonical),
      readFile(sourcePaths.validation),
    ]);
  } catch {
    throw new RuntimePublicError("assessment_dataset_source_unavailable", "storage", "Source assessment unavailable because its canonical inputs are missing.", 409);
  }
  const sourceValidation = JSON.parse(sourceValidationBytes.toString("utf8")) as Record<string, unknown>;
  const sourceFiles = sourceValidation.files as { canonical?: Record<string, unknown> } | undefined;
  const dengueSha256 = sha256(dengueBytes);
  const climateSha256 = sha256(climateBytes);
  if (
    sha256(sourceValidationBytes) !== assessment.validationRecordSha256
    || sourceValidation.workspaceId !== assessmentWorkspaceId
    || sourceValidation.datasetId !== assessment.datasetId
    || sourceValidation.workflowMode !== "assess_dataset"
    || sourceValidation.status !== "ready"
    || sourceFiles?.canonical?.dengueSha256 !== dengueSha256
    || sourceFiles?.canonical?.climateSha256 !== climateSha256
    || canonical?.dengueSha256 !== dengueSha256
    || canonical?.climateSha256 !== climateSha256
  ) {
    throw new RuntimePublicError("assessment_dataset_integrity_failed", "storage", "Dataset integrity verification failed for the assessment canonical inputs.", 409);
  }

  const sourceSnapshotSha256 = createHash("sha256").update(JSON.stringify({
    assignmentId: active.assignmentId,
    assignmentPointerSha256: active.authoritySnapshotSha256,
    assessmentId,
    assessmentCommitSha256,
    dengueSha256,
    climateSha256,
  })).digest("hex");
  return {
    assessmentId,
    assessmentWorkspaceId,
    assessmentCommitSha256,
    assignmentId: active.assignmentId,
    assignmentPointerSha256: active.authoritySnapshotSha256,
    dengue: { bytes: dengueBytes, sha256: dengueSha256, originalName: "verified-assessment-dengue.csv" },
    climate: { bytes: climateBytes, sha256: climateSha256, originalName: "verified-assessment-climate.csv" },
    sourceSnapshotSha256,
    operationalWorkspaceId: deterministicWorkspaceId(sourceSnapshotSha256),
  };
}
