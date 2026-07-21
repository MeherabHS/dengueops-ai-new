import { createHash, randomUUID } from "node:crypto";
import { readFile, rm } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type { RuntimeJobRecord, RuntimeWorkspaceMetadata, StartQuickForecastRequest, StartQuickForecastResponse } from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assertContained, jobRecordPath, runtimeCollectionPaths, workspacePaths } from "@/lib/runtime/paths";
import { createPendingJob, createWorkspaceStartMarker, initializeRuntimeRoot } from "@/lib/runtime/store";
import {resolveActiveModel} from "@/lib/runtime/active-model";

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
  return createHash("sha256").update(canonical(content)).digest("hex");
}

function recomputeDatasetId(dengue: Buffer, climate: Buffer, deploymentId: string, featureHash: string): string {
  const digest = createHash("sha256");
  for (const [label, value] of [["dengue\0", dengue], ["climate\0", climate]] as const) {
    const length = Buffer.alloc(8); length.writeBigUInt64BE(BigInt(value.length));
    digest.update(label).update(length).update(value);
  }
  digest.update(`deployment\0${deploymentId}`);
  digest.update("contract\0p1.4b-canonical-upload-v1");
  digest.update(`features\0${featureHash}`);
  return digest.digest("hex");
}

export async function POST(request: Request): Promise<Response> {
  const correlationId = randomUUID();
  try {
    const body = await request.json() as Partial<StartQuickForecastRequest> & Record<string, unknown>;
    const allowed = new Set(["workspaceId", "datasetId", "deploymentId", "validationRecordSha256"]);
    if (Object.keys(body).some(key => !allowed.has(key))) throw new RuntimePublicError("unexpected_quick_forecast_field", "validation", "The Quick Forecast request contains an unsupported field.", 400);
    if (!UUID.test(String(body.workspaceId ?? "")) || !SHA.test(String(body.datasetId ?? "")) || !SHA.test(String(body.validationRecordSha256 ?? ""))) {
      throw new RuntimePublicError("invalid_quick_forecast_request", "validation", "The Quick Forecast request identity is invalid.", 400);
    }
    const config = loadRuntimeConfig();
    if (body.deploymentId !== config.defaultDeploymentId) throw new RuntimePublicError("deployment_mismatch", "validation", "The requested deployment is unavailable.", 400);
    await initializeRuntimeRoot(config.runtimeRoot);
    const authority=await resolveActiveModel(config.repositoryRoot,config.runtimeRoot,String(body.deploymentId));
    if(!authority.quickForecastCompatible)throw new RuntimePublicError("selected_model_not_active_quick_forecast_compatible","validation","The active assigned model is not compatible with governed Quick Forecast calibration.",409);

    const workspace = workspacePaths(config.runtimeRoot, String(body.workspaceId));
    const metadata = JSON.parse(await readFile(workspace.workspaceMetadata, "utf8")) as RuntimeWorkspaceMetadata;
    if (metadata.status !== "ready" || metadata.workflowMode !== "quick_forecast") throw new RuntimePublicError("workspace_not_quick_forecast_ready", "validation", "The workspace is not ready for Quick Forecast.", 409);
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

    const policyPath = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "deployments", String(body.deploymentId), "quick_forecast_policy.json"));
    const profilePath = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "deployments", String(body.deploymentId), "profile.json"));
    const registryPath = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "candidate_models_p1.2a-v1.json"));
    const [policyBytes, profileBytes, registryBytes] = await Promise.all([readFile(policyPath), readFile(profilePath), readFile(registryPath)]);
    const policy = JSON.parse(policyBytes.toString("utf8")) as Record<string, any>;
    const profile = JSON.parse(profileBytes.toString("utf8")) as Record<string, any>;
    const registry = JSON.parse(registryBytes.toString("utf8")) as Record<string, any>;
    const policyHash = canonicalPolicySha256(policy);
    const quick = validation.eligibility?.quickForecast;
    const approvedCandidate = registry.candidates?.find((candidate: Record<string, unknown>) => candidate.model_id === policy.approved_model?.model_id);
    if (policy.policy_sha256 !== policyHash || policy.policy_status !== "active" || policy.runtime_upload_permission !== true
      || quick?.eligible !== true || quick.policySha256 !== policyHash || quick.policyId !== policy.policy_id || quick.policyVersion !== policy.policy_version
      || quick.approvedModelId !== policy.approved_model?.model_id || quick.uncertaintyStatus !== "pending_dataset_specific_calibration"
      || quick.preparednessStatus !== "unavailable_missing_planning_policy"
      || sha256(registryBytes) !== policy.candidate_registry_sha256 || approvedCandidate?.parameters_sha256 !== policy.approved_model?.parameters_sha256
      || profile.model?.model_id !== policy.approved_model?.model_id || profile.model?.model_family !== policy.approved_model?.model_family
      || profile.model?.model_parameters_sha256 !== policy.approved_model?.parameters_sha256
      || featureHash !== policy.feature_contract?.feature_order_sha256 || validation.datasetIdentity?.target !== policy.input_contract?.target
      || validation.datasetIdentity?.horizonWeeks !== policy.input_contract?.forecast_horizon_weeks) {
      throw new RuntimePublicError("quick_forecast_policy_ineligible", "validation", "The workspace is no longer eligible under the governed Quick Forecast policy.", 409);
    }

    const jobId = randomUUID(); const runId = randomUUID(); const now = new Date().toISOString();
    const collections = runtimeCollectionPaths(config.runtimeRoot);
    const marker = assertContained(workspace.metadata, path.join(workspace.metadata, "quick_forecast_started.json"));
    await createWorkspaceStartMarker(marker, { schemaVersion: "1.0", workspaceId: body.workspaceId, datasetId: body.datasetId, jobId, runId, createdAt: now });
    const authorityFields = authority.authoritySource === "committed_assignment" ? {
      activeModelAuthoritySource:authority.authoritySource, authoritySnapshotSha256:authority.authoritySnapshotSha256,
      assignmentPointerSha256:authority.assignmentPointerSha256!, assignmentId:authority.assignmentId!, assignmentCommitSha256:authority.assignmentCommitSha256!,
      resolvedModelId:authority.modelId, resolvedModelFamily:authority.modelFamily, resolvedModelParameterSha256:authority.parameterSha256,
      resolvedFeatureOrderSha256:authority.featureOrderSha256, resolvedCandidateRegistrySha256:authority.candidateRegistrySha256,
      quickPolicyId:authority.quickPolicyId, quickPolicyVersion:authority.quickPolicyVersion, quickPolicySha256:authority.quickPolicySha256,
    } as const : {
      activeModelAuthoritySource:authority.authoritySource, authoritySnapshotSha256:authority.authoritySnapshotSha256,
      historicalProfileSha256:authority.profileSha256!, resolvedModelId:authority.modelId, resolvedModelFamily:authority.modelFamily,
      resolvedModelParameterSha256:authority.parameterSha256, resolvedFeatureOrderSha256:authority.featureOrderSha256,
      resolvedCandidateRegistrySha256:authority.candidateRegistrySha256, quickPolicyId:authority.quickPolicyId,
      quickPolicyVersion:authority.quickPolicyVersion, quickPolicySha256:authority.quickPolicySha256,
    } as const;
    const job: RuntimeJobRecord = {
      schemaVersion: "1.0", jobKind: "quick_forecast", jobId, runId, workspaceId: String(body.workspaceId), datasetId: String(body.datasetId), deploymentId: String(body.deploymentId),
      workflowMode: "quick_forecast", validationRecordSha256: String(body.validationRecordSha256), policyId: policy.policy_id, policyVersion: policy.policy_version,
      policySha256: policyHash, status: "queued", progress: "queued", createdAt: now, claimedAt: null, startedAt: null, updatedAt: now,
      completedAt: null, heartbeatAt: null, workerId: null, processId: null, timeoutSeconds: config.quickForecastTimeoutSeconds,
      retryCount: 0, error: null, committedRunId: null,
      ...authorityFields,
    };
    try {
      await createPendingJob(jobRecordPath(collections.pendingJobs, jobId), job);
    } catch (error) {
      await rm(marker, { force: true }).catch(() => undefined);
      throw new RuntimePublicError("job_creation_failed", "storage", "The Quick Forecast job could not be queued.", 500, true);
    }
    const response: StartQuickForecastResponse = { ok: true, jobId, runId, status: "queued", statusUrl: `/api/runtime/jobs/${jobId}` };
    return Response.json(response, { status: 202 });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, { status: failure.status });
  }
}
