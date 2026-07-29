import { execFile } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { requireSuperUser, requireSuperUserMutation } from "@/lib/auth/authorization";
import { resolveActiveModelP2V2 } from "@/lib/runtime/active-model";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type {
  CurrentModelAssignmentResponse,
  CurrentModelAssignmentResultSuccess,
  CurrentRuntimeCandidateId,
  StartModelAssignmentRequest,
  StartModelAssignmentResponse,
} from "@/lib/runtime/contracts";
import { readVerifiedDecision } from "@/lib/runtime/decision-store";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assertContained } from "@/lib/runtime/paths";
import { validateStrictJsonSchema } from "@/lib/runtime/strict-json-schema";

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

type VerifiedCurrentAssignment = {
  response: CurrentModelAssignmentResultSuccess;
  record: Record<string, unknown>;
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

async function readStrictJson(
  filePath: string,
  schemaPath: string,
): Promise<{ bytes: Buffer; value: Record<string, unknown> }> {
  const [bytes, schemaBytes] = await Promise.all([
    readFile(filePath),
    readFile(schemaPath),
  ]);
  const value = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
  validateStrictJsonSchema(JSON.parse(schemaBytes.toString("utf8")), value);
  return { bytes, value };
}

async function verifiedCurrentAssignment(
  config: ReturnType<typeof loadRuntimeConfig>,
): Promise<VerifiedCurrentAssignment> {
  const active = await resolveActiveModelP2V2({
    repositoryRoot: config.repositoryRoot,
    runtimeRoot: config.runtimeRoot,
    deploymentId: config.defaultDeploymentId,
  });
  if (
    active.deploymentId !== config.defaultDeploymentId
    || active.authoritySource !== "committed_assignment"
    || active.assignmentAction !== "assign_selected_model"
    || active.lifecyclePolicyVersion !== "p2-v3"
    || !UUID.test(active.assignmentId)
    || !SHA.test(active.assignmentCommitSha256)
    || !SHA.test(active.authoritySnapshotSha256)
  ) {
    throw new RuntimePublicError(
      "current_assignment_integrity_error",
      "storage",
      "The current assignment authority failed integrity verification.",
      409,
    );
  }

  const assignmentRoot = assertContained(
    config.runtimeRoot,
    path.join(config.runtimeRoot, "model-assignments", active.assignmentId),
  );
  const recordPath = assertContained(
    config.runtimeRoot,
    path.join(assignmentRoot, "artifacts", "assignment_record.json"),
  );
  const commitPath = assertContained(
    config.runtimeRoot,
    path.join(assignmentRoot, "metadata", "commit.json"),
  );
  const assignmentSchemaPath = assertContained(
    config.repositoryRoot,
    path.join(config.repositoryRoot, "config", "runtime_model_assignment.schema.json"),
  );
  const commitSchemaPath = assertContained(
    config.repositoryRoot,
    path.join(config.repositoryRoot, "config", "runtime_model_assignment_commit.schema.json"),
  );

  let recordFile: Awaited<ReturnType<typeof readStrictJson>>;
  let commitFile: Awaited<ReturnType<typeof readStrictJson>>;
  try {
    [recordFile, commitFile] = await Promise.all([
      readStrictJson(recordPath, assignmentSchemaPath),
      readStrictJson(commitPath, commitSchemaPath),
    ]);
  } catch {
    throw new RuntimePublicError(
      "current_assignment_integrity_error",
      "storage",
      "The current assignment evidence failed integrity verification.",
      409,
    );
  }
  const record = recordFile.value;
  const commit = commitFile.value;
  const sourceApprovedForecastRunId = String(record.sourceApprovedForecastRunId ?? "");
  const sourceDecisionId = String(record.sourceDecisionId ?? "");
  const sourceAssessmentId = String(record.sourceAssessmentId ?? "");
  const sourceAuthorizationId = String(record.sourceAuthorizationId ?? "");
  const createdAt = String(record.assignedAt ?? "");
  if (
    record.schemaVersion !== "2.0"
    || record.assignmentId !== active.assignmentId
    || record.deploymentId !== active.deploymentId
    || record.assignmentAction !== active.assignmentAction
    || record.modelId !== active.modelId
    || record.modelFamily !== active.modelFamily
    || commit.schemaVersion !== "2.0"
    || commit.assignmentId !== active.assignmentId
    || commit.assignmentRecordSha256 !== sha256(recordFile.bytes)
    || sha256(commitFile.bytes) !== active.assignmentCommitSha256
    || !UUID.test(sourceApprovedForecastRunId)
    || !UUID.test(sourceDecisionId)
    || !UUID.test(sourceAssessmentId)
    || !UUID.test(sourceAuthorizationId)
    || !createdAt
    || !Number.isFinite(Date.parse(createdAt))
  ) {
    throw new RuntimePublicError(
      "current_assignment_integrity_error",
      "storage",
      "The current assignment evidence does not reconcile.",
      409,
    );
  }

  let decision: Awaited<ReturnType<typeof readVerifiedDecision>>;
  try {
    decision = await readVerifiedDecision(config, sourceDecisionId);
  } catch {
    throw new RuntimePublicError(
      "current_assignment_integrity_error",
      "storage",
      "The current assignment source decision failed integrity verification.",
      409,
    );
  }
  const approvedCommitPath = assertContained(
    config.runtimeRoot,
    path.join(config.runtimeRoot, "runs", sourceApprovedForecastRunId, "metadata", "commit.json"),
  );
  const approvedSchemaPath = assertContained(
    config.repositoryRoot,
    path.join(config.repositoryRoot, "config", "runtime_approved_forecast_commit.schema.json"),
  );
  let approvedCommit: Record<string, unknown>;
  try {
    approvedCommit = (await readStrictJson(approvedCommitPath, approvedSchemaPath)).value;
  } catch {
    throw new RuntimePublicError(
      "current_assignment_integrity_error",
      "storage",
      "The current assignment source forecast could not be verified.",
      409,
    );
  }
  if (
    decision.committedRunId !== sourceApprovedForecastRunId
    || decision.decision.decisionId !== sourceDecisionId
    || decision.decision.assessmentId !== sourceAssessmentId
    || decision.decision.authorizationId !== sourceAuthorizationId
    || decision.decision.selectedModelId !== active.modelId
    || approvedCommit.status !== "committed"
    || approvedCommit.runId !== sourceApprovedForecastRunId
    || approvedCommit.deploymentId !== active.deploymentId
    || approvedCommit.workflowMode !== "approved_assessment_forecast"
    || approvedCommit.decisionId !== sourceDecisionId
    || approvedCommit.decisionCommitSha256 !== decision.decisionCommitSha256
    || approvedCommit.assessmentId !== sourceAssessmentId
    || approvedCommit.authorizationId !== sourceAuthorizationId
    || approvedCommit.selectedModelId !== active.modelId
    || approvedCommit.selectedModelParameterSha256 !== active.parameterSha256
    || approvedCommit.completeReconciliation !== true
  ) {
    throw new RuntimePublicError(
      "current_assignment_integrity_error",
      "storage",
      "The current assignment source forecast does not reconcile.",
      409,
    );
  }

  return {
    record,
    response: {
      ok: true,
      assignmentId: active.assignmentId,
      status: "assigned",
      selectedCandidateId: active.modelId,
      selectedCandidateLabel: candidateLabel(active.modelId),
      assignmentCommitSha256: active.assignmentCommitSha256,
      assignmentPointerSha256: active.authoritySnapshotSha256,
      sourceApprovedForecastRunId,
      createdAt,
    },
  };
}

export async function GET(request: Request): Promise<Response> {
  const correlationId = randomUUID();
  try {
    await requireSuperUser(request);
    const config = loadRuntimeConfig();
    if (config.defaultDeploymentId !== "dhaka_south") {
      throw new RuntimePublicError("assignment_deployment_unavailable", "configuration", "Model assignment is unavailable for this deployment.", 503);
    }
    const current = await verifiedCurrentAssignment(config);
    const response: CurrentModelAssignmentResponse = current.response;
    return Response.json(response, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  }
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

    const current = await verifiedCurrentAssignment(config);
    const active = current.response;
    if (
      active.assignmentId !== cli.assignmentId
      || active.selectedCandidateId !== cli.selectedCandidateId
      || active.assignmentId === priorAuthority.assignmentId
    ) {
      throw new RuntimePublicError("assignment_publication_failed", "storage", "The governed assignment failed post-publication verification.", 409);
    }
    const record = current.record;
    if (
      record.sourceApprovedForecastRunId !== approvedForecastRunId
      || record.operatorIdentifier !== session.sub
      || record.modelId !== active.selectedCandidateId
      || record.priorAssignmentId !== priorAuthority.assignmentId
    ) {
      throw new RuntimePublicError("assignment_publication_failed", "storage", "The governed assignment failed evidence verification.", 409);
    }

    const response: StartModelAssignmentResponse = {
      ok: true,
      assignmentId: active.assignmentId,
      status: "assigned",
      selectedCandidateId: active.selectedCandidateId as CurrentRuntimeCandidateId,
      selectedCandidateLabel: active.selectedCandidateLabel,
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
