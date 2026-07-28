import { assertSameOrigin } from "@/lib/auth/authorization";
import { clearedSessionCookie } from "@/lib/auth/session";
import { RuntimePublicError } from "@/lib/runtime/errors";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<Response> {
  try {
    assertSameOrigin(request);
    return Response.json(
      { ok: true },
      { headers: { "Cache-Control": "no-store", "Set-Cookie": clearedSessionCookie() } },
    );
  } catch (error) {
    const status = error instanceof RuntimePublicError ? error.statusCode : 500;
    return Response.json(
      { ok: false, error: status === 403 ? "The request is not allowed." : "Sign out failed." },
      { status, headers: { "Cache-Control": "no-store" } },
    );
  }
}
