import { requireSuperUser } from "@/lib/auth/authorization";
import { listSubmissions, VectorStorageError } from "@/lib/community/vector-storage";
import { RuntimePublicError } from "@/lib/runtime/errors";

export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  try {
    await requireSuperUser(request);
    const url = new URL(request.url);
    const limit = url.searchParams.get("limit") === null ? 25 : Number(url.searchParams.get("limit"));
    const cursor = url.searchParams.get("cursor") ?? undefined;
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 50 || (cursor && !/^[0-9a-f-]{36}$/i.test(cursor))) throw new VectorStorageError("invalid_metadata", 400, "Pagination parameters are invalid.");
    return Response.json({ schemaVersion: "1.0", ...(await listSubmissions(limit, cursor)) }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const status = error instanceof VectorStorageError ? error.status : error instanceof RuntimePublicError ? error.statusCode : 500;
    const code = error instanceof VectorStorageError ? error.code : "unauthorized";
    return Response.json({ error: { code, message: status === 401 ? "Authentication is required." : (error as Error).message } }, { status, headers: { "Cache-Control": "no-store" } });
  }
}
