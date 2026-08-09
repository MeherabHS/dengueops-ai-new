import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type { CurrentActiveModelAuthority, RuntimeJobRecord, RuntimeJobStatus, RuntimeWorkspaceMetadata, StartQuickForecastRequest, StartQuickForecastResponse } from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assertContained, jobRecordPath, runtimeCollectionPaths, workspacePaths } from "@/lib/runtime/paths";
import { createPendingJob, createWorkspaceStartMarker, initializeRuntimeRoot } from "@/lib/runtime/store";
import {resolveActiveModel} from "@/lib/runtime/active-model";
import { loadCurrentModelLifecyclePolicy } from "@/lib/runtime/model-lifecycle-policy";
import { requireSuperUserMutation } from "@/lib/auth/authorization";
import { readBoundedJson } from "@/lib/http/request-body";

export const runtime = "nodejs";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const JOB_STATUSES = new Set<RuntimeJobStatus>(["queued", "running", "committing", "completed", "failed", "timed_out", "cancelled"]);
const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");

interface QuickForecastStartMarker {
  schemaVersion: "2.0";
  workflowType: "quick_forecast";
  workspaceId: string;
  datasetId: string;
  deploymentId: "dhaka_south";
  validationRecordSha256: string;
  expectedAssignmentPointerSha256: string;
  assignmentId: string;
  authoritySnapshotSha256: string;
  jobId: string;
  runId: string;
  statusUrl: string;
  createdAt: string;
}

const MARKER_KEYS = new Set([
  "schemaVersion", "workflowType", "workspaceId", "datasetId", "deploymentId",
  "validationRecordSha256", "expectedAssignmentPointerSha256", "assignmentId",
  "authoritySnapshotSha256", "jobId", "runId", "statusUrl", "createdAt",
]);

function markerIntegrityError(): RuntimePublicError {
  return new RuntimePublicError("quick_forecast_start_integrity_error", "storage", "The existing Quick Forecast start evidence could not be verified.", 409);
}

function parseStartMarker(bytes: Buffer): QuickForecastStartMarker {
  let value: Record<string, unknown>;
  try {
    value = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
  } catch {
    throw markerIntegrityError();
  }
  if (
    Object.keys(value).length !== MARKER_KEYS.size
    || Object.keys(value).some((key) => !MARKER_KEYS.has(key))
    || value.schemaVersion !== "2.0"
    || value.workflowType !== "quick_forecast"
    || !UUID.test(String(value.workspaceId ?? ""))
    || !SHA.test(String(value.datasetId ?? ""))
    || value.deploymentId !== "dhaka_south"
    || !SHA.test(String(value.validationRecordSha256 ?? ""))
    || !SHA.test(String(value.expectedAssignmentPointerSha256 ?? ""))
    || !UUID.test(String(value.assignmentId ?? ""))
    || !SHA.test(String(value.authoritySnapshotSha256 ?? ""))
    || !UUID.test(String(value.jobId ?? ""))
    || !UUID.test(String(value.runId ?? ""))
    || value.statusUrl !== `/api/runtime/jobs/${value.jobId}`
    || typeof value.createdAt !== "string"
    || !Number.isFinite(Date.parse(value.createdAt))
  ) throw markerIntegrityError();
  return value as unknown as QuickForecastStartMarker;
}

async function readStartMarker(markerPath: string): Promise<QuickForecastStartMarker | null> {
  try {
    return parseStartMarker(await readFile(markerPath));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
}

function verifyMarkerBindings(
  marker: QuickForecastStartMarker,
  body: StartQuickForecastRequest,
  authority: CurrentActiveModelAuthority,
): void {
  if (
    marker.workspaceId !== body.workspaceId
    || marker.datasetId !== body.datasetId
    || marker.deploymentId !== body.deploymentId
    || marker.validationRecordSha256 !== body.validationRecordSha256
    || marker.expectedAssignmentPointerSha256 !== body.expectedAssignmentPointerSha256
    || marker.assignmentId !== authority.assignmentId
    || marker.authoritySnapshotSha256 !== authority.authoritySnapshotSha256
  ) throw markerIntegrityError();
}

async function readVisibleQuickJob(runtimeRoot: string, marker: QuickForecastStartMarker): Promise<RuntimeJobRecord | null> {
  const collections = runtimeCollectionPaths(runtimeRoot);
  for (const directory of [collections.pendingJobs, collections.runningJobs, collections.completedJobs, collections.failedJobs]) {
    try {
      const job = JSON.parse(await readFile(jobRecordPath(directory, marker.jobId), "utf8")) as RuntimeJobRecord;
      return job;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw markerIntegrityError();
    }
  }
  return null;
}

function verifyRecoveredJob(job: RuntimeJobRecord, marker: QuickForecastStartMarker, authority: CurrentActiveModelAuthority): RuntimeJobStatus {
  if (
    job.jobKind !== "quick_forecast"
    || job.schemaVersion !== "2.1"
    || job.jobId !== marker.jobId
    || job.runId !== marker.runId
    || job.workspaceId !== marker.workspaceId
    || job.datasetId !== marker.datasetId
    || job.deploymentId !== marker.deploymentId
    || job.workflowMode !== marker.workflowType
    || job.validationRecordSha256 !== marker.validationRecordSha256
    || job.assignmentId !== marker.assignmentId
    || job.authoritySnapshotSha256 !== marker.authoritySnapshotSha256
    || job.assignmentCommitSha256 !== authority.assignmentCommitSha256
    || job.resolvedModelId !== authority.modelId
    || !JOB_STATUSES.has(job.status)
  ) throw markerIntegrityError();
  return job.status;
}

function successResponse(
  marker: QuickForecastStartMarker,
  authority: CurrentActiveModelAuthority,
  status: RuntimeJobStatus,
  recovered: boolean,
): StartQuickForecastResponse {
  return {
    ok: true,
    jobId: marker.jobId,
    runId: marker.runId,
    status,
    statusUrl: marker.statusUrl,
    deploymentId: marker.deploymentId,
    recovered,
    activeModelAuthority: authority,
  };
}

function canonicalPolicySha256(policy: Record<string, unknown>): string {
  const content = { ...policy };
  delete content.policy_sha256;
  delete content.policySha256;
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
    await requireSuperUserMutation(request);
    const body = await readBoundedJson<Partial<StartQuickForecastRequest> & Record<string, unknown>>(request);
    const allowed = new Set(["workspaceId", "datasetId", "deploymentId", "validationRecordSha256", "expectedAssignmentPointerSha256"]);
    if (Object.keys(body).some(key => !allowed.has(key))) throw new RuntimePublicError("unexpected_quick_forecast_field", "validation", "The Quick Forecast request contains an unsupported field.", 400);
    if (!UUID.test(String(body.workspaceId ?? "")) || !SHA.test(String(body.datasetId ?? "")) || !SHA.test(String(body.validationRecordSha256 ?? "")) || !SHA.test(String(body.expectedAssignmentPointerSha256 ?? ""))) {
      throw new RuntimePublicError("invalid_quick_forecast_request", "validation", "The Quick Forecast request identity is invalid.", 400);
    }
    const config = loadRuntimeConfig();
    if (body.deploymentId !== config.defaultDeploymentId) throw new RuntimePublicError("deployment_mismatch", "validation", "The requested deployment is unavailable.", 400);
    await initializeRuntimeRoot(config.runtimeRoot);
    const authority=await resolveActiveModel(config.repositoryRoot,config.runtimeRoot,String(body.deploymentId));
    if (authority.authoritySnapshotSha256 !== body.expectedAssignmentPointerSha256) {
      throw new RuntimePublicError("quick_forecast_assignment_conflict", "validation", "The current governed assignment changed before Quick Forecast publication.", 409);
    }

    const workspace = workspacePaths(config.runtimeRoot, String(body.workspaceId));
    const metadata = JSON.parse(await readFile(workspace.workspaceMetadata, "utf8")) as RuntimeWorkspaceMetadata;
    if (metadata.status !== "ready" || metadata.workflowMode !== "quick_forecast") throw new RuntimePublicError("workspace_not_quick_forecast_ready", "validation", "The workspace is not ready for Quick Forecast.", 409);
    if (metadata.datasetId !== body.datasetId || metadata.deploymentId !== body.deploymentId) throw new RuntimePublicError("workspace_identity_mismatch", "validation", "The workspace identity does not match the request.", 409);
    if (Date.now() - Date.parse(metadata.updatedAt) > config.workspaceMaxAgeSeconds * 1000) throw new RuntimePublicError("workspace_expired", "validation", "The validated workspace has expired.", 410);

    const validationBytes = await readFile(workspace.validation);
    if (sha256(validationBytes) !== body.validationRecordSha256) throw new RuntimePublicError("validation_record_mismatch", "validation", "The validation record has changed.", 409);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const validation = JSON.parse(validationBytes.toString("utf8")) as Record<string, any>;
    const [dengue, climate] = await Promise.all([readFile(workspace.dengueCanonical), readFile(workspace.climateCanonical)]);
    if (sha256(dengue) !== validation.files?.canonical?.dengueSha256 || sha256(climate) !== validation.files?.canonical?.climateSha256) {
      throw new RuntimePublicError("canonical_input_tampered", "validation", "Canonical uploaded data changed after validation.", 409);
    }
    const featureHash = String(validation.datasetIdentity?.featureOrderSha256 ?? "");
    if (recomputeDatasetId(dengue, climate, String(body.deploymentId), featureHash) !== body.datasetId) throw new RuntimePublicError("dataset_identity_mismatch", "validation", "The uploaded dataset identity could not be verified.", 409);

    const policyPath = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "deployments", String(body.deploymentId), "quick_forecast_policy.json"));
    const registryPath = assertContained(config.repositoryRoot, path.join(config.repositoryRoot, "config", "candidate_models.json"));
    const [policyBytes, lifecyclePolicy, registryBytes] = await Promise.all([
      readFile(policyPath),
      loadCurrentModelLifecyclePolicy(config.repositoryRoot, String(body.deploymentId)),
      readFile(registryPath),
    ]);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const policy = JSON.parse(policyBytes.toString("utf8")) as Record<string, any>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const registry = JSON.parse(registryBytes.toString("utf8")) as Record<string, any>;
    const policyHash = canonicalPolicySha256(policy);
    const quick = validation.eligibility?.quickForecast;
    const candidate = registry.candidates?.find((value: Record<string, unknown>) => value.model_id === authority.modelId);
    if (policy.schemaVersion !== "2.0" || policy.policyId !== "RUNTIME.QUICK_FORECAST.COMPATIBILITY"
      || policy.policyVersion !== lifecyclePolicy.allowedQuickForecastPolicyVersion
      || policy.policyStatus !== "active" || policy.policySha256 !== policyHash
      || policy.deploymentId !== body.deploymentId || policy.requiresActiveAssignment !== true
      || policy.profileFallbackAllowed !== false || policy.baselineQuickForecastAllowed !== false
      || quick?.eligible !== true || sha256(registryBytes) !== policy.candidateRegistrySha256
      || policy.candidateRegistrySha256 !== authority.candidateRegistrySha256
      || featureHash !== policy.featureOrderSha256 || policy.featureOrderSha256 !== authority.featureOrderSha256
      || !policy.allowedCandidateIds?.includes(authority.modelId)
      || lifecyclePolicy.policySha256 !== authority.lifecyclePolicySha256
      || lifecyclePolicy.policyId !== authority.lifecyclePolicyId
      || lifecyclePolicy.policyVersion !== authority.lifecyclePolicyVersion
      || lifecyclePolicy.allowedQuickForecastPolicyVersion !== policy.policyVersion
      || lifecyclePolicy.allowedQuickForecastPolicySha256 !== policyHash
      || candidate?.candidate_class !== "learned_model" || candidate?.selection_role !== "learned_selectable"
      || candidate?.selectable !== true || candidate?.model_family !== authority.modelFamily
      || candidate?.parameters_sha256 !== authority.parameterSha256
      || candidate?.preprocessing_identity !== authority.preprocessingIdentity
      || candidate?.feature_order_sha256 !== authority.featureOrderSha256) {
      throw new RuntimePublicError("quick_forecast_policy_ineligible", "validation", "The workspace is no longer eligible under the governed Quick Forecast policy.", 409);
    }

    const collections = runtimeCollectionPaths(config.runtimeRoot);
    const marker = assertContained(workspace.metadata, path.join(workspace.metadata, "quick_forecast_started.json"));
    const recover = async (existing: QuickForecastStartMarker): Promise<Response> => {
      verifyMarkerBindings(existing, body as StartQuickForecastRequest, authority);
      const visible = await readVisibleQuickJob(config.runtimeRoot, existing);
      if (!visible) {
        throw new RuntimePublicError("quick_forecast_publication_in_progress", "storage", "Quick Forecast publication is reserved and the job is not yet visible.", 409, true);
      }
      const status = verifyRecoveredJob(visible, existing, authority);
      return Response.json(successResponse(existing, authority, status, true), { status: 200 });
    };
    const existing = await readStartMarker(marker);
    if (existing) return await recover(existing);

    const jobId = randomUUID(); const runId = randomUUID(); const now = new Date().toISOString();
    const startMarker: QuickForecastStartMarker = {
      schemaVersion: "2.0",
      workflowType: "quick_forecast",
      workspaceId: String(body.workspaceId),
      datasetId: String(body.datasetId),
      deploymentId: "dhaka_south",
      validationRecordSha256: String(body.validationRecordSha256),
      expectedAssignmentPointerSha256: String(body.expectedAssignmentPointerSha256),
      assignmentId: authority.assignmentId,
      authoritySnapshotSha256: authority.authoritySnapshotSha256,
      jobId,
      runId,
      statusUrl: `/api/runtime/jobs/${jobId}`,
      createdAt: now,
    };
    try {
      await createWorkspaceStartMarker(marker, startMarker);
    } catch {
      const concurrentlyCreated = await readStartMarker(marker);
      if (!concurrentlyCreated) throw markerIntegrityError();
      return await recover(concurrentlyCreated);
    }
    const job: RuntimeJobRecord = {
      schemaVersion: "2.1", jobKind: "quick_forecast", jobId, runId, workspaceId: String(body.workspaceId), datasetId: String(body.datasetId), deploymentId: String(body.deploymentId),
      workflowMode: "quick_forecast", validationRecordSha256: String(body.validationRecordSha256), policyId: policy.policyId, policyVersion: policy.policyVersion,
      policySha256: policyHash, status: "queued", progress: "queued", createdAt: now, claimedAt: null, startedAt: null, updatedAt: now,
      completedAt: null, heartbeatAt: null, workerId: null, processId: null, timeoutSeconds: config.quickForecastTimeoutSeconds,
      retryCount: 0, error: null, committedRunId: null,
      activeModelAuthoritySource:authority.authoritySource,
      authoritySnapshotSha256:authority.authoritySnapshotSha256,
      assignmentId:authority.assignmentId,
      assignmentCommitSha256:authority.assignmentCommitSha256,
      assignmentAction:authority.assignmentAction,
      resolvedModelId:authority.modelId,
      resolvedModelFamily:authority.modelFamily,
      resolvedModelParameterSha256:authority.parameterSha256,
      resolvedPreprocessingIdentity:authority.preprocessingIdentity,
      resolvedFeatureOrderSha256:authority.featureOrderSha256,
      resolvedCandidateRegistrySha256:authority.candidateRegistrySha256,
      lifecyclePolicyId:authority.lifecyclePolicyId,
      lifecyclePolicyVersion:authority.lifecyclePolicyVersion,
      lifecyclePolicySha256:authority.lifecyclePolicySha256,
      quickPolicyId:policy.policyId,
      quickPolicyVersion:policy.policyVersion,
      quickPolicySha256:policyHash,
    };
    try {
      await createPendingJob(jobRecordPath(collections.pendingJobs, jobId), job);
    } catch {
      throw new RuntimePublicError("quick_forecast_publication_in_progress", "storage", "Quick Forecast publication is reserved and the job is not yet visible.", 409, true);
    }
    const response = successResponse(startMarker, authority, "queued", false);
    return Response.json(response, { status: 202 });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, { status: failure.status });
  }
}
