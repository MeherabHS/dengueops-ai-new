import { clearSignInFailures, currentSession, recordFailedSignIn, signInAllowed } from "@/lib/auth/authorization";
import { credentialsConfigured, verifyConfiguredCredentials } from "@/lib/auth/credentials";
import { createSessionToken, sessionCookie } from "@/lib/auth/session";

export const runtime = "nodejs";

const genericFailure = () => Response.json(
  { ok: false, error: "Invalid username or password." },
  { status: 401, headers: { "Cache-Control": "no-store" } },
);

export async function GET(request: Request): Promise<Response> {
  const session = await currentSession(request);
  return Response.json(
    { authenticated: session?.role === "super_user", role: session?.role ?? null },
    { headers: { "Cache-Control": "no-store" } },
  );
}

export async function POST(request: Request): Promise<Response> {
  if (!signInAllowed(request)) return genericFailure();
  if (!credentialsConfigured()) {
    return Response.json(
      { ok: false, error: "Authentication is unavailable." },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
  let body: Record<string, unknown>;
  try {
    body = await request.json() as Record<string, unknown>;
  } catch {
    recordFailedSignIn(request);
    return genericFailure();
  }
  if (Object.keys(body).sort().join("|") !== "password|username"
    || typeof body.username !== "string"
    || typeof body.password !== "string"
    || !(await verifyConfiguredCredentials(body.username, body.password))) {
    recordFailedSignIn(request);
    return genericFailure();
  }
  clearSignInFailures(request);
  const token = await createSessionToken(body.username.trim());
  return Response.json(
    { ok: true, role: "super_user" },
    { headers: { "Cache-Control": "no-store", "Set-Cookie": sessionCookie(token) } },
  );
}
