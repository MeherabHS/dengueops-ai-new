import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { readFile } from "node:fs/promises";
import { loadRuntimeConfig, type RuntimeConfig } from "@/lib/runtime/config";
import type { ApprovedForecastJobRecord, JobStatusResponse, RuntimeJobRecord } from "@/lib/runtime/contracts";
import { readVerifiedDecision } from "@/lib/runtime/decision-store";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assertContained, jobRecordPath, runtimeCollectionPaths } from "@/lib/runtime/paths";

export const runtime = "nodejs";

const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");

async function verifiedApprovedForecastCommitSha256(
  config: RuntimeConfig,
  job: ApprovedForecastJobRecord,
): Promise<string> {
  if (job.status !== "completed" || !job.committedRunId || job.committedRunId !== job.runId) {
    throw new RuntimePublicError("approved_forecast_completion_invalid", "storage", "The completed approved forecast identity is invalid.", 409);
  }
  const decision = await readVerifiedDecision(config, job.decisionId);
  if (
    decision.decisionCommitSha256 !== job.decisionCommitSha256 ||
    decision.committedRunId !== job.committedRunId ||
    decision.decision.decisionId !== job.decisionId ||
    decision.decision.assessmentId !== job.assessmentId ||
    decision.decision.assessmentCommitSha256 !== job.assessmentCommitSha256 ||
    decision.decision.authorizationId !== job.authorizationId ||
    decision.decision.selectedModelId !== job.selectedModelId ||
    decision.decision.selectedModelParameterSha256 !== job.selectedModelParameterSha256
  ) {
    throw new RuntimePublicError("approved_forecast_binding_invalid", "storage", "The approved forecast failed decision binding verification.", 409);
  }
  const runs = runtimeCollectionPaths(config.runtimeRoot).runs;
  const commitPath = assertContained(runs, path.join(runs, job.committedRunId, "metadata", "commit.json"));
  let bytes: Buffer;
  let commit: Record<string, unknown>;
  try {
    bytes = await readFile(commitPath);
    commit = JSON.parse(bytes.toString("utf8")) as Record<string, unknown>;
  } catch {
    throw new RuntimePublicError("approved_forecast_commit_unavailable", "storage", "The approved forecast commit could not be verified.", 409);
  }
  if (
    commit.status !== "committed" ||
    commit.runId !== job.committedRunId ||
    commit.jobId !== job.jobId ||
    commit.datasetId !== job.datasetId ||
    commit.deploymentId !== job.deploymentId ||
    commit.workflowMode !== "approved_assessment_forecast" ||
    commit.decisionId !== job.decisionId ||
    commit.decisionCommitSha256 !== job.decisionCommitSha256 ||
    commit.assessmentId !== job.assessmentId ||
    commit.assessmentCommitSha256 !== job.assessmentCommitSha256 ||
    commit.authorizationId !== job.authorizationId ||
    commit.selectedModelId !== job.selectedModelId ||
    commit.selectedModelParameterSha256 !== job.selectedModelParameterSha256 ||
    commit.completeReconciliation !== true
  ) {
    throw new RuntimePublicError("approved_forecast_commit_mismatch", "storage", "The approved forecast commit identity does not match the completed job.", 409);
  }
  return sha256(bytes);
}

export async function GET(_request: Request, context: RouteContext<"/api/runtime/jobs/[jobId]">): Promise<Response> {
  const correlationId = randomUUID();
  try {
    const { jobId } = await context.params;
    const config = loadRuntimeConfig();
    const paths = runtimeCollectionPaths(config.runtimeRoot);
    let job: RuntimeJobRecord | null = null;
    for (const directory of [paths.pendingJobs, paths.runningJobs, paths.completedJobs, paths.failedJobs]) {
      try {
        job = JSON.parse(await readFile(jobRecordPath(directory, jobId), "utf8")) as RuntimeJobRecord;
        break;
      } catch {
        // Continue through the bounded job collections.
      }
    }
    if (!job) throw new RuntimePublicError("job_not_found", "validation", "The requested runtime job was not found.", 404);

    let response: JobStatusResponse;
    if (job.jobKind === "dataset_assessment") {
      response = { ok: true, jobKind: "dataset_assessment", jobId: job.jobId, assessmentId: job.assessmentId, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: job.error?.retryable ?? false, error: job.error, committedAssessmentId: job.committedAssessmentId };
    } else if (job.jobKind === "approved_forecast") {
      const base = { ok: true as const, jobKind: "approved_forecast" as const, jobId: job.jobId, runId: job.runId, decisionId: job.decisionId, assessmentId: job.assessmentId, authorizationId: job.authorizationId, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: false as const, error: job.error };
      response = job.status === "completed"
        ? { ...base, status: "completed", committedRunId: job.committedRunId ?? "", approvedForecastCommitSha256: await verifiedApprovedForecastCommitSha256(config, job) }
        : { ...base, status: job.status, committedRunId: null };
    } else if (job.jobKind === "forecast_outcome") {
      response = { ok: true, jobKind: "forecast_outcome", jobId: job.jobId, outcomeId: job.outcomeId, workflowMode: job.workflowMode, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: job.error?.retryable ?? false, error: job.error, committedOutcomeId: job.committedOutcomeId };
    } else if (job.jobKind === "degradation_evidence") {
      response = { ok: true, jobKind: "degradation_evidence", jobId: job.jobId, evidenceId: job.evidenceId, workflowMode: job.workflowMode, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: false, error: job.error, committedEvidenceId: job.committedEvidenceId };
    } else if (job.jobKind === "model_lifecycle") {
      response = { ok: true, jobKind: "model_lifecycle", jobId: job.jobId, lifecycleDecisionId: job.lifecycleDecisionId, workflowMode: job.workflowMode, action: job.action, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: false, error: job.error, committedLifecycleDecisionId: job.committedLifecycleDecisionId };
    } else {
      response = {
        ok: true, jobKind: "quick_forecast", jobId: job.jobId, runId: job.runId, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: job.error?.retryable ?? false, error: job.error, committedRunId: job.committedRunId,
        ...((job.schemaVersion === "2.0" || job.schemaVersion === "2.1") && "assignmentAction" in job ? { activeModelAuthority: {
          deploymentId: job.deploymentId, authoritySource: job.activeModelAuthoritySource, modelId: job.resolvedModelId,
          modelFamily: job.resolvedModelFamily, parameterSha256: job.resolvedModelParameterSha256,
          preprocessingIdentity: job.resolvedPreprocessingIdentity, candidateRegistrySha256: job.resolvedCandidateRegistrySha256,
          featureOrderSha256: job.resolvedFeatureOrderSha256, assignmentId: job.assignmentId,
          assignmentCommitSha256: job.assignmentCommitSha256, assignmentAction: job.assignmentAction,
          lifecyclePolicyId: job.lifecyclePolicyId, lifecyclePolicyVersion: job.lifecyclePolicyVersion,
          lifecyclePolicySha256: job.lifecyclePolicySha256, authoritySnapshotSha256: job.authoritySnapshotSha256,
        } } : {}),
      };
    }
    return Response.json(response, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  }
}
