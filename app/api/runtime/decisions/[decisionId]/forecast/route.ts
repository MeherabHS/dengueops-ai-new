import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { mkdir, open, rm } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type {
  ApprovedForecastJobRecord,
  StartApprovedForecastResponse,
} from "@/lib/runtime/contracts";
import { readVerifiedDecision } from "@/lib/runtime/decision-store";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import {
  authorizationPaths,
  jobRecordPath,
  runtimeCollectionPaths,
} from "@/lib/runtime/paths";
import {
  createPendingJob,
  initializeRuntimeRoot,
  writeExclusive,
} from "@/lib/runtime/store";
export const runtime = "nodejs";
function authorized(request: Request, configured: string) {
  const provided =
    request.headers.get("x-dengueops-internal-decision-secret") ?? "";
  return (
    configured.length >= 16 &&
    timingSafeEqual(
      createHash("sha256").update(configured).digest(),
      createHash("sha256").update(provided).digest(),
    )
  );
}
export async function POST(
  request: Request,
  context: { params: Promise<{ decisionId: string }> },
): Promise<Response> {
  const correlationId = randomUUID();
  let lock: Awaited<ReturnType<typeof open>> | null = null,
    lockPath = "";
  try {
    const config = loadRuntimeConfig(false);
    if (
      !config.internalDecisionEnabled ||
      !config.internalDecisionSecret ||
      !config.internalOperatorId
    ) {
      throw new RuntimePublicError(
        "internal_decision_disabled",
        "configuration",
        "Trusted internal model decisions are disabled.",
        503,
      );
    }
    if (!authorized(request, config.internalDecisionSecret)) {
      throw new RuntimePublicError(
        "internal_decision_forbidden",
        "validation",
        "The trusted internal decision credential is invalid.",
        403,
      );
    }
    const { decisionId } = await context.params;
    const body = (await request.json()) as Record<string, unknown>;
    if (
      Object.keys(body).join("|") !== "expectedDecisionCommitSha256" ||
      !/^[a-f0-9]{64}$/.test(String(body.expectedDecisionCommitSha256 ?? ""))
    )
      throw new RuntimePublicError(
        "invalid_approved_forecast_request",
        "validation",
        "The approved forecast request is invalid.",
        400,
      );
    await initializeRuntimeRoot(config.runtimeRoot);
    const verified = await readVerifiedDecision(config, decisionId);
    if (verified.decisionCommitSha256 !== body.expectedDecisionCommitSha256)
      throw new RuntimePublicError(
        "decision_commit_changed",
        "validation",
        "The decision differs from the reviewed committed record.",
        409,
      );
    if (
      !verified.authorization ||
      !verified.decision.forecastAuthorized ||
      verified.authorizationStatus !== "available"
    )
      throw new RuntimePublicError(
        "forecast_authorization_unavailable",
        "validation",
        "The one-run forecast authorization is not available.",
        409,
      );
    if (Date.now() > Date.parse(verified.authorization.expiresAt))
      throw new RuntimePublicError(
        "forecast_authorization_expired",
        "validation",
        "The one-run forecast authorization has expired.",
        409,
      );
    const auth = authorizationPaths(
      config.runtimeRoot,
      verified.authorization.authorizationId,
    );
    lockPath = auth.lock;
    await mkdir(path.dirname(lockPath), { recursive: true, mode: 0o700 });
    try {
      lock = await open(lockPath, "wx", 0o600);
    } catch {
      throw new RuntimePublicError(
        "forecast_authorization_locked",
        "storage",
        "The forecast authorization is already being reserved.",
        409,
      );
    }
    const jobId = randomUUID(),
      runId = randomUUID(),
      eventId = randomUUID(),
      createdAt = new Date().toISOString();
    await mkdir(auth.state, { recursive: true, mode: 0o700 });
    await writeExclusive(
      auth.reservation,
      Buffer.from(
        `${JSON.stringify({ schemaVersion: "1.0", authorizationId: verified.authorization.authorizationId, decisionId, eventType: "reserved", eventId, createdAt, jobId, runId }, null, 2)}\n`,
      ),
    );
    const collections = runtimeCollectionPaths(config.runtimeRoot);
    const job: ApprovedForecastJobRecord = {
      schemaVersion: "1.0",
      jobKind: "approved_forecast",
      jobId,
      runId,
      decisionId,
      decisionCommitSha256: verified.decisionCommitSha256,
      authorizationId: verified.authorization.authorizationId,
      assessmentId: verified.decision.assessmentId,
      assessmentCommitSha256: verified.decision.assessmentCommitSha256,
      workspaceId: verified.decision.assessmentId,
      datasetId: verified.decision.datasetId,
      deploymentId: verified.decision.deploymentId,
      selectedModelId: verified.decision.selectedModelId,
      selectedModelParameterSha256:
        verified.decision.selectedModelParameterSha256,
      workflowMode: "approved_assessment_forecast",
      validationRecordSha256: verified.decision.validationRecordSha256,
      status: "queued",
      progress: "queued",
      createdAt,
      claimedAt: null,
      startedAt: null,
      updatedAt: createdAt,
      completedAt: null,
      heartbeatAt: null,
      workerId: null,
      processId: null,
      timeoutSeconds: config.approvedForecastTimeoutSeconds,
      retryCount: 0,
      error: null,
      committedRunId: null,
    };
    await createPendingJob(jobRecordPath(collections.pendingJobs, jobId), job);
    const response: StartApprovedForecastResponse = {
      ok: true,
      jobId,
      runId,
      decisionId,
      authorizationId: job.authorizationId,
      status: "queued",
      statusUrl: `/api/runtime/jobs/${jobId}`,
    };
    return Response.json(response, {
      status: 202,
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, {
      status: failure.status,
      headers: { "Cache-Control": "no-store" },
    });
  } finally {
    if (lock) {
      await lock.close();
      await rm(lockPath, { force: true });
    }
  }
}
