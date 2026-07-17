import { createHash, randomUUID } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type { DatasetAssessmentJobRecord, RuntimeWorkspaceMetadata, StartAssessmentRequest, StartAssessmentResponse } from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assertContained, jobRecordPath, runtimeCollectionPaths, workspacePaths } from "@/lib/runtime/paths";
import { createPendingJob, createWorkspaceStartMarker, initializeRuntimeRoot } from "@/lib/runtime/store";

export const runtime = "nodejs";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");

function canonicalPolicySha256(policy: Record<string, unknown>): string {
  const { policy_sha256: _ignored, ...content } = policy;
  const canonical = (value: unknown): string => Array.isArray(value)
    ? `[${value.map(canonical).join(",")}]`
    : value && typeof value === "object"
      ? `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`
      : JSON.stringify(value);
  return sha256(Buffer.from(canonical(content), "utf8"));
}

function recomputeDatasetId(dengue: Buffer, climate: Buffer, deploymentId: string, featureHash: string): string {
  const digest = createHash("sha256");
  for (const [label, value] of [["dengue\0", dengue], ["climate\0", climate]] as const) {
    const length = Buffer.alloc(8); length.writeBigUInt64BE(BigInt(value.length));
    digest.update(label).update(length).update(value);
  }
  return digest.update(`deployment\0${deploymentId}`).update("contract\0p1.4b-canonical-upload-v1").update(`features\0${featureHash}`).digest("hex");
}

function success(assessmentId: string, jobId: string): StartAssessmentResponse {
  return { ok: true, assessmentId, jobId, status: "queued", statusUrl: `/api/runtime/jobs/${jobId}`, assessmentUrl: `/api/runtime/assessments/${assessmentId}` };
}

async function existingMarker(marker: string, workspaceId: string, datasetId: string): Promise<StartAssessmentResponse | null> {
  try {
    const value = JSON.parse(await readFile(marker, "utf8")) as Record<string, unknown>;
    if (value.schemaVersion !== "1.0" || value.workspaceId !== workspaceId || value.datasetId !== datasetId
      || !UUID.test(String(value.assessmentId ?? "")) || !UUID.test(String(value.jobId ?? ""))) {
      throw new RuntimePublicError("corrupt_assessment_start_marker", "storage", "The existing assessment start marker failed integrity checks.", 409);
    }
    return success(String(value.assessmentId), String(value.jobId));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    if (error instanceof RuntimePublicError) throw error;
    throw new RuntimePublicError("corrupt_assessment_start_marker", "storage", "The existing assessment start marker failed integrity checks.", 409);
  }
}

export async function POST(request: Request): Promise<Response> {
  const correlationId = randomUUID();
  try {
    const body = await request.json() as Partial<StartAssessmentRequest> & Record<string, unknown>;
    const allowed = new Set(["workspaceId", "datasetId", "deploymentId", "validationRecordSha256"]);
    if (Object.keys(body).some(key => !allowed.has(key))) throw new RuntimePublicError("unexpected_assessment_field", "validation", "The assessment request contains an unsupported field.", 400);
    if (!UUID.test(String(body.workspaceId ?? "")) || !SHA.test(String(body.datasetId ?? "")) || !SHA.test(String(body.validationRecordSha256 ?? ""))) {
      throw new RuntimePublicError("invalid_assessment_request", "validation", "The assessment request identity is invalid.", 400);
    }
    const config = loadRuntimeConfig();
    if (body.deploymentId !== config.defaultDeploymentId) throw new RuntimePublicError("deployment_mismatch", "validation", "The requested deployment is unavailable.", 400);
    await initializeRuntimeRoot(config.runtimeRoot);
    const workspace = workspacePaths(config.runtimeRoot, String(body.workspaceId));
    const metadata = JSON.parse(await readFile(workspace.workspaceMetadata, "utf8")) as RuntimeWorkspaceMetadata;
    if (metadata.status !== "ready" || metadata.workflowMode !== "assess_dataset") throw new RuntimePublicError("workspace_not_assessment_ready", "validation", "The workspace is not ready for dataset assessment.", 409);
    if (metadata.datasetId !== body.datasetId || metadata.deploymentId !== body.deploymentId) throw new RuntimePublicError("workspace_identity_mismatch", "validation", "The workspace identity does not match the request.", 409);
    if (Date.now() - Date.parse(metadata.updatedAt) > config.workspaceMaxAgeSeconds * 1000) throw new RuntimePublicError("workspace_expired", "validation", "The validated workspace has expired.", 410);

    const validationBytes = await readFile(workspace.validation);
    if (sha256(validationBytes) !== body.validationRecordSha256) throw new RuntimePublicError("validation_record_mismatch", "validation", "The validation record has changed.", 409);
    const validation = JSON.parse(validationBytes.toString("utf8")) as Record<string, any>;
    const [dengue, climate] = await Promise.all([readFile(workspace.dengueCanonical), readFile(workspace.climateCanonical)]);
    if (sha256(dengue) !== validation.files?.canonical?.dengueSha256 || sha256(climate) !== validation.files?.canonical?.climateSha256) {
      throw new RuntimePublicError("canonical_input_tampered", "validation", "Canonical uploaded data changed after validation.", 409);
    }
    const featureHash = String(validation.datasetIdentity?.featureOrderSha256 ?? "");
    if (recomputeDatasetId(dengue, climate, String(body.deploymentId), featureHash) !== body.datasetId) throw new RuntimePublicError("dataset_identity_mismatch", "validation", "The uploaded dataset identity could not be verified.", 409);

    const policyPath = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "deployments", String(body.deploymentId), "assessment_policy.json"));
    const registryPath = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "candidate_models.json"));
    const [policyBytes, registryBytes] = await Promise.all([readFile(policyPath), readFile(registryPath)]);
    const policy = JSON.parse(policyBytes.toString("utf8")) as Record<string, any>;
    const registry = JSON.parse(registryBytes.toString("utf8")) as Record<string, any>;
    const policyHash = canonicalPolicySha256(policy);
    const assess = validation.eligibility?.assessDataset;
    const governedCandidates = policy.candidate_eligibility_policy?.candidates ?? [];
    const registryCandidates = registry.candidates ?? [];
    const candidatesMatch = governedCandidates.length === 7 && registryCandidates.length === 7 && governedCandidates.every((candidate: Record<string, unknown>, index: number) =>
      candidate.model_id === registryCandidates[index]?.model_id && candidate.parameters_sha256 === registryCandidates[index]?.parameters_sha256);
    const labelledRows = Number(validation.counts?.labelledRows);
    const availableFoldCount = Number(assess?.availableFoldCount);
    const plannedFoldCount = Number(assess?.plannedFoldCount);
    const selectedStart = Number(assess?.selectedValidationStartIndex);
    const selectedEnd = Number(assess?.selectedValidationEndIndex);
    const foldPolicy = policy.fold_policy ?? {};
    if (policy.policy_sha256 !== policyHash || policy.policy_status !== "active" || policy.deployment_id !== body.deploymentId
      || policy.policy_id !== "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE" || policy.policy_version !== "p2-v1"
      || foldPolicy.policy_id !== "RUNTIME.ASSESSMENT.DYNAMIC_EXPANDING_FOLDS" || foldPolicy.policy_version !== "p2-v1"
      || foldPolicy.initial_training_rows !== 104 || foldPolicy.embargo_rows !== 1 || foldPolicy.validation_rows_per_fold !== 1
      || foldPolicy.step_size_weeks !== 1 || foldPolicy.target_horizon_weeks !== 2 || foldPolicy.minimum_labelled_rows !== 157
      || foldPolicy.minimum_fold_count !== 52 || foldPolicy.maximum_fold_count !== 68
      || foldPolicy.fold_selection_rule !== "most_recent_contiguous_validation_indexes_up_to_maximum_fold_count"
      || sha256(registryBytes) !== policy.candidate_registry?.sha256 || registry.candidate_registry_version !== policy.candidate_registry?.version
      || !candidatesMatch || featureHash !== policy.feature_contract?.feature_order_sha256
      || validation.datasetIdentity?.target !== policy.input_contract?.target || validation.datasetIdentity?.horizonWeeks !== policy.input_contract?.horizon_weeks
      || validation.normalization?.canonicalContractVersion !== policy.input_contract?.canonical_contract_version
      || !Number.isSafeInteger(labelledRows) || labelledRows < 157 || assess?.eligible !== true || assess.assessmentStatus !== "full_assessment_eligible"
      || !Number.isSafeInteger(availableFoldCount) || availableFoldCount !== Math.max(0, labelledRows - 105) || availableFoldCount < 52
      || !Number.isSafeInteger(plannedFoldCount) || plannedFoldCount !== Math.min(availableFoldCount, 68) || plannedFoldCount < 52 || plannedFoldCount > 68
      || assess.minimumFoldCount !== 52 || assess.maximumFoldCount !== 68 || assess.foldCapApplied !== (availableFoldCount > 68)
      || selectedStart !== labelledRows - plannedFoldCount || selectedEnd !== labelledRows - 1
      || assess.candidateSetStatus !== "complete_candidate_set"
      || assess.policyId !== policy.policy_id || assess.policyVersion !== policy.policy_version || assess.policySha256 !== policyHash
      || assess.recommendationStatus !== "evidence_only" || assess.recommendationStrength !== "not_available"
      || assess.approvalRequired !== true || assess.approvalEnabled !== false
      || !Object.values(assess.candidateEligibility ?? {}).every((candidate: any) => candidate.eligible === true)) {
      throw new RuntimePublicError("assessment_policy_ineligible", "validation", "The workspace is no longer eligible under the governed dataset-assessment policy.", 409);
    }

    const marker = assertContained(workspace.metadata, path.join(workspace.metadata, "assessment_started.json"));
    const duplicate = await existingMarker(marker, String(body.workspaceId), String(body.datasetId));
    if (duplicate) return Response.json(duplicate, { status: 202 });
    const assessmentId = randomUUID(); const jobId = randomUUID(); const now = new Date().toISOString();
    const markerValue = { schemaVersion: "1.0", workspaceId: body.workspaceId, datasetId: body.datasetId, assessmentId, jobId, createdAt: now };
    try {
      await createWorkspaceStartMarker(marker, markerValue);
    } catch {
      const raced = await existingMarker(marker, String(body.workspaceId), String(body.datasetId));
      if (raced) return Response.json(raced, { status: 202 });
      throw new RuntimePublicError("assessment_marker_creation_failed", "storage", "The assessment start marker could not be created.", 500, true);
    }
    const job: DatasetAssessmentJobRecord = {
      schemaVersion: "1.0", jobKind: "dataset_assessment", jobId, assessmentId, workspaceId: String(body.workspaceId), datasetId: String(body.datasetId),
      deploymentId: String(body.deploymentId), workflowMode: "assess_dataset", validationRecordSha256: String(body.validationRecordSha256),
      assessmentPolicyId: policy.policy_id, assessmentPolicyVersion: policy.policy_version, assessmentPolicySha256: policyHash,
      candidateRegistrySha256: sha256(registryBytes), status: "queued", progress: "queued", createdAt: now, claimedAt: null,
      startedAt: null, updatedAt: now, completedAt: null, heartbeatAt: null, workerId: null, processId: null,
      timeoutSeconds: config.assessmentTimeoutSeconds, retryCount: 0, error: null, committedAssessmentId: null,
    };
    try {
      const collections = runtimeCollectionPaths(config.runtimeRoot);
      await createPendingJob(jobRecordPath(collections.pendingJobs, jobId), job);
    } catch {
      await rm(marker, { force: true }).catch(() => undefined);
      throw new RuntimePublicError("assessment_job_creation_failed", "storage", "The dataset-assessment job could not be queued.", 500, true);
    }
    return Response.json(success(assessmentId, jobId), { status: 202 });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, { status: failure.status });
  }
}
