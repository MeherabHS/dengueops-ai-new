import { createHash, randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { lstat, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type {
  RuntimeValidationAuthorityBinding,
  RuntimeValidationResponseSuccess,
  RuntimeWorkspaceMetadata,
  WorkflowMode,
} from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assertContained, workspacePaths, type WorkspacePaths } from "@/lib/runtime/paths";
import {
  appendWorkspaceEvent,
  createWorkspace,
  initializeRuntimeRoot,
  writeExclusive,
  writeWorkspaceMetadata,
} from "@/lib/runtime/store";
import {resolveActiveModel} from "@/lib/runtime/active-model";
import { inspectCsvUpload } from "@/lib/runtime/uploads";
import { requireSuperUserMutation } from "@/lib/auth/authorization";
import { resolveCurrentAssessmentDataset, type VerifiedAssessmentDatasetSource } from "@/lib/runtime/assessment-dataset-source";
import { readBoundedFormData, readBoundedJson } from "@/lib/http/request-body";

export const runtime = "nodejs";

function validationAuthorityMatches(
  binding: RuntimeValidationAuthorityBinding,
  current: Awaited<ReturnType<typeof resolveActiveModel>>,
): boolean {
  return binding.authoritySource === "committed_assignment"
    && binding.assignmentId === current.assignmentId
    && binding.assignmentCommitSha256 === current.assignmentCommitSha256
    && binding.authoritySnapshotSha256 === current.authoritySnapshotSha256
    && binding.assignedCandidateId === current.modelId
    && binding.candidateRegistrySha256 === current.candidateRegistrySha256
    && binding.featureOrderSha256 === current.featureOrderSha256
    && binding.lifecyclePolicyId === current.lifecyclePolicyId
    && binding.lifecyclePolicyVersion === current.lifecyclePolicyVersion
    && binding.lifecyclePolicySha256 === current.lifecyclePolicySha256
    && binding.operationalPolicyId === "RUNTIME.QUICK_FORECAST.COMPATIBILITY"
    && binding.operationalPolicyVersion === "p2-v2"
    && /^[a-f0-9]{64}$/.test(binding.operationalPolicySha256);
}

function singleString(form: FormData, name: string): string {
  const values = form.getAll(name);
  if (values.length !== 1 || typeof values[0] !== "string" || !values[0].trim()) {
    throw new RuntimePublicError("invalid_multipart_fields", "upload", `Exactly one ${name} field is required.`, 400);
  }
  return values[0].trim();
}

function singleFile(form: FormData, name: string): File {
  const values = form.getAll(name);
  if (values.length !== 1 || !(values[0] instanceof File)) {
    throw new RuntimePublicError("invalid_multipart_files", "upload", `Exactly one ${name} CSV file is required.`, 400);
  }
  return values[0];
}

async function runPythonValidation(input: {
  pythonExecutable: string;
  repositoryRoot: string;
  runtimeRoot: string;
  timeoutMs: number;
  paths: WorkspacePaths;
  workspaceId: string;
  createdAt: string;
  deploymentId: string;
  workflowMode: WorkflowMode;
}): Promise<void> {
  const script = path.join(/* turbopackIgnore: true */ input.repositoryRoot, "analytics", "runtime_validate.py");
  const args = [
    script,
    "--workspace-root", input.paths.root,
    "--runtime-root", input.runtimeRoot,
    "--workspace-id", input.workspaceId,
    "--created-at", input.createdAt,
    "--dengue-input", input.paths.dengueOriginal,
    "--climate-input", input.paths.climateOriginal,
    "--canonical-dengue-output", input.paths.dengueCanonical,
    "--canonical-climate-output", input.paths.climateCanonical,
    "--validation-output", input.paths.validation,
    "--deployment-id", input.deploymentId,
    "--workflow-mode", input.workflowMode,
  ];
  await new Promise<void>((resolve, reject) => {
    const child = spawn(input.pythonExecutable, args, {
      shell: false,
      cwd: input.repositoryRoot,
      windowsHide: true,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGKILL");
    }, input.timeoutMs);
    child.stdout.on("data", (chunk: Buffer) => {
      if (Buffer.concat(stdout).length < 1_048_576) stdout.push(Buffer.from(chunk));
    });
    child.stderr.on("data", (chunk: Buffer) => {
      if (Buffer.concat(stderr).length < 1_048_576) stderr.push(Buffer.from(chunk));
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", async (code) => {
      clearTimeout(timer);
      await Promise.all([
        writeFile(input.paths.stdout, Buffer.concat(stdout), { mode: 0o600 }),
        writeFile(input.paths.stderr, Buffer.concat(stderr), { mode: 0o600 }),
      ]).catch(() => undefined);
      if (timedOut) {
        reject(new RuntimePublicError("validation_timeout", "validation", "Authoritative validation timed out.", 504, true));
      } else if (code !== 0) {
        reject(new RuntimePublicError("python_validation_failed", "validation", "Authoritative validation could not be completed.", 500, true));
      } else resolve();
    });
  });
}

async function verifiedValidationResponse(input: {
  config: ReturnType<typeof loadRuntimeConfig>;
  paths: WorkspacePaths;
  requestedWorkflowMode: WorkflowMode;
}): Promise<RuntimeValidationResponseSuccess> {
  const validation = JSON.parse(await readFile(input.paths.validation, "utf8")) as Omit<RuntimeValidationResponseSuccess, "ok" | "workflowMode" | "activeModelAuthority"> & {
    schemaVersion: string;
    workflowMode?: unknown;
    activeModelAuthority?: RuntimeValidationAuthorityBinding;
  };
  const validationRecordSha256 = createHash("sha256").update(await readFile(input.paths.validation)).digest("hex");
  if (validation.status !== "ready" && validation.status !== "invalid") {
    throw new RuntimePublicError("invalid_validation_output", "validation", "Authoritative validation returned an invalid status.", 500, true);
  }
  const verifiedWorkflowMode = validation.workflowMode;
  if (verifiedWorkflowMode !== "quick_forecast" && verifiedWorkflowMode !== "assess_dataset") {
    throw new RuntimePublicError("invalid_validation_output", "validation", "Authoritative validation returned an invalid workflow mode.", 500, true);
  }
  if (verifiedWorkflowMode !== input.requestedWorkflowMode) {
    throw new RuntimePublicError("invalid_validation_output", "validation", "Authoritative validation did not match the requested workflow mode.", 500, true);
  }
  const currentAuthority = await resolveActiveModel(input.config.repositoryRoot, input.config.runtimeRoot, validation.deploymentId);
  if (verifiedWorkflowMode === "quick_forecast" && (
    !validation.activeModelAuthority
    || !validationAuthorityMatches(validation.activeModelAuthority, currentAuthority)
    || validation.eligibility.quickForecast.assignedCandidateId !== currentAuthority.modelId
  )) {
    throw new RuntimePublicError(
      "quick_validation_authority_mismatch",
      "validation",
      "Quick Forecast validation could not be reconciled with the current governed assignment.",
      409,
    );
  }
  return {
    ok: true,
    status: validation.status,
    workflowMode: verifiedWorkflowMode,
    workspaceId: validation.workspaceId,
    datasetId: validation.datasetId,
    deploymentId: validation.deploymentId,
    validationRecordSha256,
    ...(validation.acceptedPeriod ? { acceptedPeriod: validation.acceptedPeriod } : {}),
    counts: validation.counts,
    issues: validation.issues,
    eligibility: validation.eligibility,
    activeModelAuthority: currentAuthority,
  };
}

async function recoverAssessmentHandoff(
  config: ReturnType<typeof loadRuntimeConfig>,
  paths: WorkspacePaths,
  source: VerifiedAssessmentDatasetSource,
): Promise<RuntimeValidationResponseSuccess | null> {
  const markerPath = assertContained(paths.metadata, path.join(paths.metadata, "assessment-source.json"));
  let markerBytes: Buffer;
  try {
    markerBytes = await readFile(markerPath);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw error;
  }
  const marker = JSON.parse(markerBytes.toString("utf8")) as Record<string, unknown>;
  const [dengueBytes, climateBytes] = await Promise.all([readFile(paths.dengueOriginal), readFile(paths.climateOriginal)]);
  if (
    Object.keys(marker).sort().join("|") !== "assessmentCommitSha256|assessmentId|assessmentWorkspaceId|assignmentId|assignmentPointerSha256|sourceSnapshotSha256"
    || marker.assessmentId !== source.assessmentId
    || marker.assessmentWorkspaceId !== source.assessmentWorkspaceId
    || marker.assessmentCommitSha256 !== source.assessmentCommitSha256
    || marker.assignmentId !== source.assignmentId
    || marker.assignmentPointerSha256 !== source.assignmentPointerSha256
    || marker.sourceSnapshotSha256 !== source.sourceSnapshotSha256
    || createHash("sha256").update(dengueBytes).digest("hex") !== source.dengue.sha256
    || createHash("sha256").update(climateBytes).digest("hex") !== source.climate.sha256
  ) {
    throw new RuntimePublicError("assessment_dataset_integrity_failed", "storage", "Dataset integrity verification failed for the recovered operational workspace.", 409);
  }
  return await verifiedValidationResponse({ config, paths, requestedWorkflowMode: "quick_forecast" });
}

export async function POST(request: Request): Promise<Response> {
  const correlationId = randomUUID();
  let paths: WorkspacePaths | undefined;
  let metadata: RuntimeWorkspaceMetadata | undefined;
  let handoffLockPath: string | undefined;
  try {
    await requireSuperUserMutation(request);
    const config = loadRuntimeConfig();
    const contentLength = Number(request.headers.get("content-length") ?? 0);
    if (contentLength > config.maxUploadBytes * 2 + 1_048_576) {
      throw new RuntimePublicError("request_too_large", "upload", "The multipart upload exceeds the configured request limit.", 413);
    }
    const contentType = request.headers.get("content-type") ?? "";
    let source: VerifiedAssessmentDatasetSource | null = null;
    let deploymentId: string;
    let workflowMode: WorkflowMode;
    let dengue: { bytes: Buffer; originalName: string; sizeBytes: number; sha256: string };
    let climate: { bytes: Buffer; originalName: string; sizeBytes: number; sha256: string };
    if (contentType.toLowerCase().startsWith("application/json")) {
      const body = await readBoundedJson<Record<string, unknown>>(request);
      if (Object.keys(body).sort().join("|") !== "source" || body.source !== "current_assignment_assessment") {
        throw new RuntimePublicError("invalid_assessment_dataset_handoff", "validation", "The assessment-dataset handoff request is invalid.", 400);
      }
      source = await resolveCurrentAssessmentDataset(config);
      deploymentId = config.defaultDeploymentId;
      workflowMode = "quick_forecast";
      dengue = { ...source.dengue, sizeBytes: source.dengue.bytes.length };
      climate = { ...source.climate, sizeBytes: source.climate.bytes.length };
    } else {
      if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
        throw new RuntimePublicError("multipart_required", "upload", "The validation endpoint requires multipart/form-data or a bounded governed dataset-source intent.", 415);
      }
      const form = await readBoundedFormData(request, config.maxUploadBytes * 2 + 1_048_576);
      const permitted = new Set(["dengueFile", "climateFile", "deploymentId", "workflowMode"]);
      for (const key of form.keys()) {
        if (!permitted.has(key)) throw new RuntimePublicError("unexpected_multipart_field", "upload", "The upload contains an unexpected field.", 400);
      }
      deploymentId = singleString(form, "deploymentId");
      if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(deploymentId) || deploymentId !== config.defaultDeploymentId) {
        throw new RuntimePublicError("unsupported_deployment", "validation", "The requested deployment is not available for runtime validation.", 400);
      }
      const workflowModeValue = singleString(form, "workflowMode");
      if (workflowModeValue !== "quick_forecast" && workflowModeValue !== "assess_dataset") {
        throw new RuntimePublicError("invalid_workflow_mode", "validation", "The workflow mode is invalid.", 400);
      }
      workflowMode = workflowModeValue;
      [dengue, climate] = await Promise.all([
        inspectCsvUpload(singleFile(form, "dengueFile"), config.maxUploadBytes),
        inspectCsvUpload(singleFile(form, "climateFile"), config.maxUploadBytes),
      ]);
    }
    await initializeRuntimeRoot(config.runtimeRoot);
    const workspaceId = source?.operationalWorkspaceId ?? randomUUID();
    paths = workspacePaths(config.runtimeRoot, workspaceId);
    if (source) {
      const lockRoot = assertContained(config.runtimeRoot, path.join(config.runtimeRoot, "locks", "assessment-dataset-handoffs"));
      await mkdir(lockRoot, { recursive: true, mode: 0o700 });
      handoffLockPath = assertContained(lockRoot, path.join(lockRoot, `${workspaceId}.lock`));
      try {
        await mkdir(handoffLockPath, { mode: 0o700 });
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === "EEXIST") {
          throw new RuntimePublicError("assessment_dataset_handoff_in_progress", "storage", "The assessed dataset is already being prepared for operational validation.", 409, true);
        }
        throw error;
      }
      let workspaceExists = false;
      try {
        workspaceExists = (await lstat(paths.root)).isDirectory();
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
      if (workspaceExists) {
        const recovered = await recoverAssessmentHandoff(config, paths, source);
        if (!recovered) {
          throw new RuntimePublicError("assessment_dataset_integrity_failed", "storage", "Dataset integrity verification failed for the existing handoff workspace.", 409);
        }
        return Response.json(recovered, { status: recovered.status === "ready" ? 200 : 422, headers: { "Cache-Control": "no-store" } });
      }
    }
    await createWorkspace(paths);
    const now = new Date().toISOString();
    metadata = {
      schemaVersion: "1.0",
      workspaceId,
      correlationId,
      deploymentId,
      workflowMode,
      status: "uploaded",
      createdAt: now,
      updatedAt: now,
      originalFiles: {
        dengue: { originalName: dengue.originalName, storedName: "dengue.csv", sizeBytes: dengue.sizeBytes, sha256: dengue.sha256 },
        climate: { originalName: climate.originalName, storedName: "climate.csv", sizeBytes: climate.sizeBytes, sha256: climate.sha256 },
      },
    };
    await Promise.all([
      writeExclusive(paths.dengueOriginal, dengue.bytes),
      writeExclusive(paths.climateOriginal, climate.bytes),
    ]);
    if (source) {
      const markerPath = assertContained(paths.metadata, path.join(paths.metadata, "assessment-source.json"));
      await writeExclusive(markerPath, Buffer.from(`${JSON.stringify({
        assessmentId: source.assessmentId,
        assessmentWorkspaceId: source.assessmentWorkspaceId,
        assessmentCommitSha256: source.assessmentCommitSha256,
        assignmentId: source.assignmentId,
        assignmentPointerSha256: source.assignmentPointerSha256,
        sourceSnapshotSha256: source.sourceSnapshotSha256,
      }, null, 2)}\n`, "utf8"));
    }
    await writeWorkspaceMetadata(paths, metadata);
    await appendWorkspaceEvent(paths, { timestamp: now, correlationId, workspaceId, eventType: "workspace_created" });
    await appendWorkspaceEvent(paths, {
      timestamp: now,
      correlationId,
      workspaceId,
      eventType: source ? "assessment_dataset_materialized" : "upload_saved",
      metadata: { dengueSizeBytes: dengue.sizeBytes, climateSizeBytes: climate.sizeBytes },
    });
    metadata = { ...metadata, status: "validating", updatedAt: new Date().toISOString() };
    await writeWorkspaceMetadata(paths, metadata);
    await appendWorkspaceEvent(paths, { timestamp: metadata.updatedAt, correlationId, workspaceId, eventType: "validation_started" });
    await runPythonValidation({
      pythonExecutable: config.pythonExecutable,
      repositoryRoot: config.repositoryRoot,
      runtimeRoot: config.runtimeRoot,
      timeoutMs: config.validationTimeoutMs,
      paths,
      workspaceId,
      createdAt: metadata.createdAt,
      deploymentId,
      workflowMode,
    });
    const response = await verifiedValidationResponse({ config, paths, requestedWorkflowMode: workflowMode });
    metadata = {
      ...metadata,
      status: response.status,
      datasetId: response.datasetId,
      updatedAt: new Date().toISOString(),
    };
    await writeWorkspaceMetadata(paths, metadata);
    await appendWorkspaceEvent(paths, {
      timestamp: metadata.updatedAt,
      correlationId,
      workspaceId,
      eventType: "validation_completed",
      metadata: { status: response.status, issueCount: response.issues.length },
    });
    await appendWorkspaceEvent(paths, {
      timestamp: metadata.updatedAt,
      correlationId,
      workspaceId,
      eventType: response.status === "ready" ? "workspace_ready" : "workspace_invalid",
    });
    return Response.json(response, { status: response.status === "ready" ? 200 : 422, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    if (paths && metadata) {
      const timestamp = new Date().toISOString();
      const invalidMetadata = { ...metadata, status: "invalid" as const, updatedAt: timestamp };
      await writeWorkspaceMetadata(paths, invalidMetadata).catch(() => undefined);
      await appendWorkspaceEvent(paths, {
        timestamp,
        correlationId,
        workspaceId: metadata.workspaceId,
        eventType: "validation_failed",
        metadata: { code: error instanceof RuntimePublicError ? error.code : "internal_failure" },
      }).catch(() => undefined);
    }
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  } finally {
    if (handoffLockPath) await rm(handoffLockPath, { recursive: true, force: true }).catch(() => undefined);
  }
}
