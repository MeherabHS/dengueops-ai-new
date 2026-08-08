import "server-only";

import { createHash, timingSafeEqual } from "node:crypto";

export type CommunityApiScope = "community:read" | "vector:submit";
export type CommunityApiErrorCode = "unauthorized" | "forbidden_scope" | "rate_limited";

export class CommunityApiError extends Error {
  constructor(public readonly code: CommunityApiErrorCode, public readonly status: number, message: string) {
    super(message);
  }
}

const windows = new Map<string, { count: number; expiresAt: number }>();
const WINDOW_MS = 60_000;
const LIMITS: Record<CommunityApiScope, number> = { "community:read": 60, "vector:submit": 10 };

// These scoped keys are extractable application-integration credentials, not end-user
// authentication. A production mobile rollout should replace them with short-lived tokens.

function equalSecret(left: string, right: string): boolean {
  const a = createHash("sha256").update(left).digest();
  const b = createHash("sha256").update(right).digest();
  return timingSafeEqual(a, b);
}

function sourceKey(request: Request): string {
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim()
    || request.headers.get("x-real-ip")?.trim() || "local-unknown";
  return createHash("sha256").update(ip.slice(0, 256)).digest("hex");
}

function configuredKeys(): Record<CommunityApiScope, string> {
  const read = process.env.DENGUEOPS_COMMUNITY_READ_API_KEY?.trim() ?? "";
  const submit = process.env.DENGUEOPS_VECTOR_SUBMIT_API_KEY?.trim() ?? "";
  if (read.length < 16 || submit.length < 16 || equalSecret(read, submit)) {
    throw new CommunityApiError("unauthorized", 401, "A valid API credential is required.");
  }
  return { "community:read": read, "vector:submit": submit };
}

function suppliedBearer(request: Request): string {
  const match = /^Bearer\s+([^\s]+)$/i.exec(request.headers.get("authorization") ?? "");
  if (!match) throw new CommunityApiError("unauthorized", 401, "A valid API credential is required.");
  return match[1];
}

export function authenticateCommunityApi(request: Request, requiredScope: CommunityApiScope, now = Date.now()): void {
  const supplied = suppliedBearer(request);
  const keys = configuredKeys();
  if (!equalSecret(supplied, keys[requiredScope])) {
    const other: CommunityApiScope = requiredScope === "community:read" ? "vector:submit" : "community:read";
    const wrongScope = equalSecret(supplied, keys[other]);
    throw new CommunityApiError(wrongScope ? "forbidden_scope" : "unauthorized", wrongScope ? 403 : 401, wrongScope ? "This credential does not permit the requested operation." : "A valid API credential is required.");
  }
  const credential = createHash("sha256").update(supplied).digest("hex");
  const key = `${requiredScope}:${credential}:${sourceKey(request)}`;
  for (const [candidate, value] of windows) if (value.expiresAt <= now) windows.delete(candidate);
  while (windows.size >= 2048) windows.delete(windows.keys().next().value!);
  const entry = windows.get(key);
  if (entry && entry.expiresAt > now && entry.count >= LIMITS[requiredScope]) {
    throw new CommunityApiError("rate_limited", 429, "Too many requests. Try again later.");
  }
  windows.set(key, entry && entry.expiresAt > now
    ? { count: entry.count + 1, expiresAt: entry.expiresAt }
    : { count: 1, expiresAt: now + WINDOW_MS });
}

export function communityApiErrorResponse(error: unknown): Response {
  if (error instanceof CommunityApiError) {
    return Response.json({ error: { code: error.code, message: error.message } }, { status: error.status, headers: { "Cache-Control": "no-store" } });
  }
  return Response.json({ error: { code: "storage_unavailable", message: "The requested service is temporarily unavailable." } }, { status: 503, headers: { "Cache-Control": "no-store" } });
}
