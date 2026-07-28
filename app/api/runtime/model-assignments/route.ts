import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { requireSuperUserMutation } from "@/lib/auth/authorization";
import { resolveActiveModelP2V2 } from "@/lib/runtime/active-model";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type {
  CurrentRuntimeCandidateId,
  StartModelAssignmentRequest,
  StartModelAssignmentResponse,
} from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assertContained } from "@/lib/runtime/paths";

export const runtime = "nodejs";

const runFile = promisify(execFile);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");
const REQUEST_KEYS = [
  "approvedForecastRunId",
  "assignmentAcknowledged",
  "expectedApprovedForecastCommitSha256",
  "expectedAssignmentPointerSha256",
  "reason",
].sort();

type CliResult = {
  ok: boolean;
  assignmentId?: string;
  selectedCandidateId?: string;
};

function exactRequest(body: Record<string, unknown>): body is Record<keyof StartModelAssignmentRequest, unknown> {
  return Object.keys(body).sort().join("|") === REQUEST_KEYS.join("|");
}

function candidateLabel(candidateId: string): string {
  return candidateId.split("_").map(part => part ? `${part[0].toUpperCase()}${part.slice(1)}` : part).join(" ");
}

async function verifiedPointer(config: ReturnType<typeof loadRuntimeConfig>, expectedSha: string) {
  const authority = await resolveActiveModelP2V2({
    repositoryRoot: config.repositoryRoot,
    runtimeRoot: config.runtimeRoot,
    deploymentId: config.defaultDeploymentId,
  });
  if (authority.authoritySnapshotSha256 !== expectedSha) {
    throw new RuntimePublicError(
      "assignment_pointer_conflict",
      "storage",
      "The active assignment changed after this workflow was reviewed.",
      409,
    );
  }
  return authority;
}

export async function POST(request: Request): Promise<Response> {
  const correlationId = randomUUID();
  let lockPath: string | null = null;
  let lockAcquired = false;
  try {
    const session = await requireSuperUserMutation(request);
    const body = await request.json() as Record<string, unknown>;
    if (!exactRequest(body)) {
      throw new RuntimePublicError("invalid_assignment_request", "validation", "The assignment request contains unsupported fields.", 400);
    }
    const approvedForecastRunId = String(body.approvedForecastRunId ?? "");
    const expectedApprovedForecastCommitSha256 = String(body.expectedApprovedForecastCommitSha256 ?? "");
    const expectedAssignmentPointerSha256 = String(body.expectedAssignmentPointerSha256 ?? "");
    const reason = String(body.reason ?? "").trim();
    if (
      !UUID.test(approvedForecastRunId)
      || !SHA.test(expectedApprovedForecastCommitSha256)
      || !SHA.test(expectedAssignmentPointerSha256)
      || !reason
      || reason.length > 1000
      || body.assignmentAcknowledged !== true
    ) {
      throw new RuntimePublicError("invalid_assignment_request", "validation", "The assignment request is invalid.", 400);
    }

    const config = loadRuntimeConfig();
    if (config.defaultDeploymentId !== "dhaka_south") {
      throw new RuntimePublicError("assignment_deployment_unavailable", "configuration", "Model assignment is unavailable for this deployment.", 503);
    }
    const priorAuthority = await verifiedPointer(config, expectedAssignmentPointerSha256);
    const approvedCommitPath = assertContained(
      config.runtimeRoot,
      path.join(config.runtimeRoot, "runs", approvedForecastRunId, "metadata", "commit.json"),
    );
    let approvedCommitBytes: Buffer;
    try {
      approvedCommitBytes = await readFile(approvedCommitPath);
    } catch {
      throw new RuntimePublicError("approved_forecast_unavailable", "storage", "The approved forecast could not be verified.", 409);
    }
    if (sha256(approvedCommitBytes) !== expectedApprovedForecastCommitSha256) {
      throw new RuntimePublicError("approved_forecast_commit_mismatch", "storage", "The approved forecast changed after review.", 409);
    }

    const assignmentRoot = assertContained(
      config.runtimeRoot,
      path.join(config.runtimeRoot, "deployments", config.defaultDeploymentId, "model-assignment"),
    );
    lockPath = assertContained(config.runtimeRoot, path.join(assignmentRoot, ".publication-lock"));
    try {
      await mkdir(lockPath);
      lockAcquired = true;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "EEXIST") {
        throw new RuntimePublicError("assignment_publication_in_progress", "storage", "Another assignment publication is in progress.", 409);
      }
      throw error;
    }

    await verifiedPointer(config, expectedAssignmentPointerSha256);
    if (sha256(await readFile(approvedCommitPath)) !== expectedApprovedForecastCommitSha256) {
      throw new RuntimePublicError("approved_forecast_commit_mismatch", "storage", "The approved forecast changed after review.", 409);
    }
    const cliPath = assertContained(
      config.repositoryRoot,
      path.join(config.repositoryRoot, "analytics", "runtime_model_assignment_cli.py"),
    );
    let stdout: string;
    try {
      const result = await runFile(config.pythonExecutable, [
        cliPath,
        "--approved-forecast-run-id", approvedForecastRunId,
        "--reason", reason,
        "--acknowledgement", "true",
        "--runtime-root", config.runtimeRoot,
        "--repository-root", config.repositoryRoot,
        "--operator-identifier", session.sub,
      ], {
        cwd: config.repositoryRoot,
        encoding: "utf8",
        timeout: 120_000,
        maxBuffer: 64 * 1024,
        windowsHide: true,
      });
      stdout = result.stdout;
    } catch {
      throw new RuntimePublicError("assignment_publication_failed", "storage", "The governed assignment could not be published.", 409);
    }
    let cli: CliResult;
    try {
      cli = JSON.parse(stdout) as CliResult;
    } catch {
      throw new RuntimePublicError("assignment_publication_failed", "storage", "The governed assignment could not be verified.", 409);
    }
    if (cli.ok !== true || !UUID.test(String(cli.assignmentId ?? ""))) {
      throw new RuntimePublicError("assignment_publication_failed", "storage", "The governed assignment could not be verified.", 409);
    }

    const active = await resolveActiveModelP2V2({
      repositoryRoot: config.repositoryRoot,
      runtimeRoot: config.runtimeRoot,
      deploymentId: config.defaultDeploymentId,
    });
    if (
      active.assignmentId !== cli.assignmentId
      || active.modelId !== cli.selectedCandidateId
      || active.assignmentId === priorAuthority.assignmentId
    ) {
      throw new RuntimePublicError("assignment_publication_failed", "storage", "The governed assignment failed post-publication verification.", 409);
    }
    const recordPath = assertContained(
      config.runtimeRoot,
      path.join(config.runtimeRoot, "model-assignments", active.assignmentId, "artifacts", "assignment_record.json"),
    );
    const record = JSON.parse(await readFile(recordPath, "utf8")) as Record<string, unknown>;
    if (
      record.sourceApprovedForecastRunId !== approvedForecastRunId
      || record.operatorIdentifier !== session.sub
      || record.modelId !== active.modelId
      || record.priorAssignmentId !== priorAuthority.assignmentId
    ) {
      throw new RuntimePublicError("assignment_publication_failed", "storage", "The governed assignment failed evidence verification.", 409);
    }

    const response: StartModelAssignmentResponse = {
      ok: true,
      assignmentId: active.assignmentId,
      status: "assigned",
      selectedCandidateId: active.modelId as CurrentRuntimeCandidateId,
      selectedCandidateLabel: candidateLabel(active.modelId),
      sourceApprovedForecastRunId: approvedForecastRunId,
      createdAt: String(record.assignedAt),
      previousAssignmentPresent: record.priorAssignmentId !== null,
    };
    return Response.json(response, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  } finally {
    if (lockPath && lockAcquired) await rm(lockPath, { recursive: true, force: true }).catch(() => undefined);
  }
}
