import { createHash, randomUUID } from "node:crypto";
import { lstat, readFile } from "node:fs/promises";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type { DatasetAssessmentResponse, DatasetAssessmentResultSuccess } from "@/lib/runtime/contracts";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { assessmentPaths } from "@/lib/runtime/paths";

export const runtime = "nodejs";

const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");

export async function GET(_request: Request, context: { params: Promise<{ assessmentId: string }> }): Promise<Response> {
  try {
    const { assessmentId } = await context.params;
    const config = loadRuntimeConfig(false);
    const paths = assessmentPaths(config.runtimeRoot, assessmentId);
    const stat = await lstat(paths.committed).catch(() => null);
    if (!stat?.isDirectory() || stat.isSymbolicLink()) throw new RuntimePublicError("assessment_not_found", "validation", "The requested committed assessment was not found.", 404);
    const commitBytes = await readFile(`${paths.committed}/metadata/commit.json`);
    const commit = JSON.parse(commitBytes.toString("utf8")) as Record<string, any>;
    if (commit.status !== "committed" || commit.assessmentId !== assessmentId || commit.latestPointerUpdated !== false) {
      throw new RuntimePublicError("assessment_integrity_error", "storage", "The committed assessment failed integrity validation.", 409);
    }
    const hashes = commit.artifactHashes as Record<string, string>;
    for (const [name, expected] of Object.entries(hashes)) {
      const bytes = await readFile(`${paths.committed}/artifacts/${name}`);
      if (sha256(bytes) !== expected) throw new RuntimePublicError("assessment_integrity_error", "storage", "The committed assessment failed artifact verification.", 409);
    }
    const summaryBytes = await readFile(`${paths.committed}/artifacts/assessment_summary.json`);
    if (sha256(summaryBytes) !== hashes["assessment_summary.json"]) throw new RuntimePublicError("assessment_integrity_error", "storage", "The assessment summary hash is invalid.", 409);
    const summary = JSON.parse(summaryBytes.toString("utf8")) as Omit<DatasetAssessmentResultSuccess, "ok">;
    if (summary.assessmentId !== assessmentId || summary.datasetId !== commit.datasetId || summary.jobId !== commit.jobId
      || summary.assessmentStatus !== "assessment_complete" || summary.approvalEnabled !== false || summary.adoptionStatus !== "not_adopted") {
      throw new RuntimePublicError("assessment_integrity_error", "storage", "The assessment summary identity is invalid.", 409);
    }
    const response: DatasetAssessmentResponse = { ok: true, ...summary, integrity: { assessmentSummarySha256: sha256(summaryBytes), assessmentCommitSha256: sha256(commitBytes) } };
    return Response.json(response, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error, randomUUID());
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  }
}
