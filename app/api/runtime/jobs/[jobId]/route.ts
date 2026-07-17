import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type { JobStatusResponse, RuntimeJobRecord } from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { jobRecordPath, runtimeCollectionPaths } from "@/lib/runtime/paths";

export const runtime = "nodejs";

export async function GET(_request: Request, context: RouteContext<"/api/runtime/jobs/[jobId]">): Promise<Response> {
  try {
    const { jobId } = await context.params;
    const config = loadRuntimeConfig(); const paths = runtimeCollectionPaths(config.runtimeRoot);
    let job: RuntimeJobRecord | null = null;
    for (const directory of [paths.pendingJobs, paths.runningJobs, paths.completedJobs, paths.failedJobs]) {
      try { job = JSON.parse(await readFile(jobRecordPath(directory, jobId), "utf8")) as RuntimeJobRecord; break; } catch { /* continue */ }
    }
    if (!job) throw new RuntimePublicError("job_not_found", "validation", "The requested runtime job was not found.", 404);
    const response: JobStatusResponse = job.jobKind === "dataset_assessment"
      ? { ok: true, jobKind: "dataset_assessment", jobId: job.jobId, assessmentId: job.assessmentId, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: job.error?.retryable ?? false, error: job.error, committedAssessmentId: job.committedAssessmentId }
      : job.jobKind === "approved_forecast"
      ? { ok: true, jobKind: "approved_forecast", jobId: job.jobId, runId: job.runId, decisionId: job.decisionId, assessmentId: job.assessmentId, authorizationId: job.authorizationId, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: false, error: job.error, committedRunId: job.committedRunId }
      : job.jobKind === "forecast_outcome"
      ? { ok: true, jobKind: "forecast_outcome", jobId: job.jobId, outcomeId: job.outcomeId, workflowMode: job.workflowMode, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: job.error?.retryable ?? false, error: job.error, committedOutcomeId: job.committedOutcomeId }
      : job.jobKind === "degradation_evidence"
      ? {ok:true,jobKind:"degradation_evidence",jobId:job.jobId,evidenceId:job.evidenceId,workflowMode:job.workflowMode,status:job.status,progress:job.progress,createdAt:job.createdAt,startedAt:job.startedAt,updatedAt:job.updatedAt,completedAt:job.completedAt,retryable:false,error:job.error,committedEvidenceId:job.committedEvidenceId}
      : { ok: true, jobKind: "quick_forecast", jobId: job.jobId, runId: job.runId, status: job.status, progress: job.progress, createdAt: job.createdAt, startedAt: job.startedAt, updatedAt: job.updatedAt, completedAt: job.completedAt, retryable: job.error?.retryable ?? false, error: job.error, committedRunId: job.committedRunId };
    return Response.json(response, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error, randomUUID());
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  }
}
