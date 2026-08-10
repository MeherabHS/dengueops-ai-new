import { requireSuperUserMutation } from "@/lib/auth/authorization";
import type { VectorGovernanceReason } from "@/lib/community/contracts";
import { deleteSubmission, excludeSubmission, VectorStorageError } from "@/lib/community/vector-storage";
import { readBoundedJson, RequestBodyError } from "@/lib/http/request-body";
import { RuntimePublicError } from "@/lib/runtime/errors";

export const runtime = "nodejs";

const REASONS = new Set<VectorGovernanceReason>([
  "test_submission", "duplicate", "unusable_image", "invalid_location",
  "irrelevant_content", "user_request", "other",
]);

function reason(value: unknown): VectorGovernanceReason {
  if (typeof value !== "string" || !REASONS.has(value as VectorGovernanceReason)) {
    throw new VectorStorageError("invalid_metadata", 400, "A valid governance reason is required.");
  }
  return value as VectorGovernanceReason;
}

function exactKeys(value: Record<string, unknown>, allowed: string[]): void {
  if (Object.keys(value).some(key => !allowed.includes(key))) {
    throw new VectorStorageError("invalid_metadata", 400, "The governance request is invalid.");
  }
}

function failure(error: unknown): Response {
  const status = error instanceof VectorStorageError ? error.status
    : error instanceof RequestBodyError ? error.status
      : error instanceof RuntimePublicError ? error.statusCode : 503;
  const code = error instanceof VectorStorageError ? error.code
    : error instanceof RequestBodyError ? error.code
      : status === 401 ? "unauthorized" : status === 403 ? "forbidden" : "storage_unavailable";
  const message = status === 401 ? "Authentication is required."
    : status === 403 ? "The request is not allowed."
      : error instanceof Error ? error.message : "Vector governance is temporarily unavailable.";
  return Response.json({ error: { code, message } }, { status, headers: { "Cache-Control": "no-store" } });
}

export async function PATCH(
  request: Request,
  { params }: { params: Promise<{ submissionId: string }> },
): Promise<Response> {
  try {
    const session = await requireSuperUserMutation(request);
    const body = await readBoundedJson<Record<string, unknown>>(request, 4 * 1024);
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new VectorStorageError("invalid_metadata", 400, "The governance request is invalid.");
    exactKeys(body, ["reason", "note"]);
    const selectedReason = reason(body.reason);
    const note = body.note === undefined || body.note === null || body.note === "" ? null : body.note;
    if ((note !== null && (typeof note !== "string" || note.trim().length > 500))
      || (selectedReason !== "other" && note !== null)) throw new VectorStorageError("invalid_metadata", 400, "The governance note is invalid.");
    const { submissionId } = await params;
    const submission = await excludeSubmission(submissionId, selectedReason, typeof note === "string" ? note.trim() : null, session.sub);
    return Response.json({ schemaVersion: "1.0", submissionId, analysisDisposition: submission.analysisDisposition }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return failure(error);
  }
}

export async function DELETE(
  request: Request,
  { params }: { params: Promise<{ submissionId: string }> },
): Promise<Response> {
  try {
    const session = await requireSuperUserMutation(request);
    const body = await readBoundedJson<Record<string, unknown>>(request, 4 * 1024);
    if (!body || typeof body !== "object" || Array.isArray(body)) throw new VectorStorageError("invalid_metadata", 400, "The deletion request is invalid.");
    exactKeys(body, ["reason", "confirmation"]);
    if (body.confirmation !== "delete_permanently") throw new VectorStorageError("invalid_metadata", 400, "Explicit permanent-deletion confirmation is required.");
    const { submissionId } = await params;
    const result = await deleteSubmission(submissionId, reason(body.reason), session.sub);
    return Response.json({ schemaVersion: "1.0", submissionId, status: result.status, deletedAt: result.tombstone.deletedAt }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return failure(error);
  }
}
