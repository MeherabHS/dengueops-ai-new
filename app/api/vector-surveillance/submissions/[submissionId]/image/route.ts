import { requireSuperUser } from "@/lib/auth/authorization";
import { readImage, VectorStorageError } from "@/lib/community/vector-storage";
import { RuntimePublicError } from "@/lib/runtime/errors";

export const runtime = "nodejs";

export async function GET(request: Request, { params }: { params: Promise<{ submissionId: string }> }): Promise<Response> {
  try {
    await requireSuperUser(request);
    const { submissionId } = await params;
    const image = await readImage(submissionId);
    return new Response(new Uint8Array(image.bytes), { headers: { "Cache-Control": "private, no-store", "Content-Type": image.metadata.contentType, "Content-Disposition": `inline; filename="${submissionId}"`, "X-Content-Type-Options": "nosniff" } });
  } catch (error) {
    const status = error instanceof VectorStorageError ? error.status : error instanceof RuntimePublicError ? error.statusCode : 500;
    return Response.json({ error: { code: status === 401 ? "unauthorized" : "not_found", message: status === 401 ? "Authentication is required." : "The submission was not found." } }, { status, headers: { "Cache-Control": "no-store" } });
  }
}
