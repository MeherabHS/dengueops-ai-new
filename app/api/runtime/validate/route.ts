import { createHash, randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type {
  RuntimeValidationResponseSuccess,
  RuntimeWorkspaceMetadata,
  WorkflowMode,
} from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { workspacePaths, type WorkspacePaths } from "@/lib/runtime/paths";
import {
  appendWorkspaceEvent,
  createWorkspace,
  initializeRuntimeRoot,
  writeExclusive,
  writeWorkspaceMetadata,
} from "@/lib/runtime/store";
import {resolveActiveModel} from "@/lib/runtime/active-model";
import { inspectCsvUpload } from "@/lib/runtime/uploads";

export const runtime = "nodejs";

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

export async function POST(request: Request): Promise<Response> {
  const correlationId = randomUUID();
  let paths: WorkspacePaths | undefined;
  let metadata: RuntimeWorkspaceMetadata | undefined;
  try {
    const config = loadRuntimeConfig();
    const contentLength = Number(request.headers.get("content-length") ?? 0);
    if (contentLength > config.maxUploadBytes * 2 + 1_048_576) {
      throw new RuntimePublicError("request_too_large", "upload", "The multipart upload exceeds the configured request limit.", 413);
    }
    const contentType = request.headers.get("content-type") ?? "";
    if (!contentType.toLowerCase().startsWith("multipart/form-data")) {
      throw new RuntimePublicError("multipart_required", "upload", "The validation endpoint requires multipart/form-data.", 415);
    }
    const form = await request.formData();
    const permitted = new Set(["dengueFile", "climateFile", "deploymentId", "workflowMode"]);
    for (const key of form.keys()) {
      if (!permitted.has(key)) throw new RuntimePublicError("unexpected_multipart_field", "upload", "The upload contains an unexpected field.", 400);
    }
    const deploymentId = singleString(form, "deploymentId");
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(deploymentId) || deploymentId !== config.defaultDeploymentId) {
      throw new RuntimePublicError("unsupported_deployment", "validation", "The requested deployment is not available for runtime validation.", 400);
    }
    const workflowModeValue = singleString(form, "workflowMode");
    if (workflowModeValue !== "quick_forecast" && workflowModeValue !== "assess_dataset") {
      throw new RuntimePublicError("invalid_workflow_mode", "validation", "The workflow mode is invalid.", 400);
    }
    const workflowMode: WorkflowMode = workflowModeValue;
    const [dengue, climate] = await Promise.all([
      inspectCsvUpload(singleFile(form, "dengueFile"), config.maxUploadBytes),
      inspectCsvUpload(singleFile(form, "climateFile"), config.maxUploadBytes),
    ]);
    await initializeRuntimeRoot(config.runtimeRoot);
    const workspaceId = randomUUID();
    paths = workspacePaths(config.runtimeRoot, workspaceId);
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
    await writeWorkspaceMetadata(paths, metadata);
    await appendWorkspaceEvent(paths, { timestamp: now, correlationId, workspaceId, eventType: "workspace_created" });
    await appendWorkspaceEvent(paths, {
      timestamp: now,
      correlationId,
      workspaceId,
      eventType: "upload_saved",
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
    const validation = JSON.parse(await readFile(paths.validation, "utf8")) as Omit<RuntimeValidationResponseSuccess, "ok"> & { schemaVersion: string };
    const validationRecordSha256 = createHash("sha256").update(await readFile(paths.validation)).digest("hex");
    if (validation.status !== "ready" && validation.status !== "invalid") {
      throw new RuntimePublicError("invalid_validation_output", "validation", "Authoritative validation returned an invalid status.", 500, true);
    }
    metadata = {
      ...metadata,
      status: validation.status,
      datasetId: validation.datasetId,
      updatedAt: new Date().toISOString(),
    };
    await writeWorkspaceMetadata(paths, metadata);
    await appendWorkspaceEvent(paths, {
      timestamp: metadata.updatedAt,
      correlationId,
      workspaceId,
      eventType: "validation_completed",
      metadata: { status: validation.status, issueCount: validation.issues.length },
    });
    await appendWorkspaceEvent(paths, {
      timestamp: metadata.updatedAt,
      correlationId,
      workspaceId,
      eventType: validation.status === "ready" ? "workspace_ready" : "workspace_invalid",
    });
    const response: RuntimeValidationResponseSuccess = {
      ok: true,
      status: validation.status,
      workspaceId: validation.workspaceId,
      datasetId: validation.datasetId,
      deploymentId: validation.deploymentId,
      validationRecordSha256,
      ...(validation.acceptedPeriod ? { acceptedPeriod: validation.acceptedPeriod } : {}),
      counts: validation.counts,
      issues: validation.issues,
      eligibility: validation.eligibility,
      activeModelAuthority:(({authoritySource,authoritySnapshotSha256,modelId,bootstrapRequired,quickForecastCompatible})=>({authoritySource,authoritySnapshotSha256,modelId,bootstrapRequired,quickForecastCompatible}))(await resolveActiveModel(config.repositoryRoot,config.runtimeRoot,validation.deploymentId)),
    };
    return Response.json(response, { status: validation.status === "ready" ? 200 : 422 });
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
    return Response.json(failure.body, { status: failure.status });
  }
}
