import "server-only";

import { createHash, timingSafeEqual } from "node:crypto";
import { RuntimePublicError } from "@/lib/runtime/errors";
import { sessionCookieName, type SuperUserSession, verifySessionToken } from "./session";

const THROTTLE_WINDOW_MS = 15 * 60 * 1000;
const THROTTLE_MAX_FAILURES = 5;
const THROTTLE_MAX_KEYS = 512;
const attempts = new Map<string, { failures: number; expiresAt: number }>();

function cookieValue(request: Request, name: string): string | undefined {
  const cookie = request.headers.get("cookie") ?? "";
  for (const part of cookie.split(";")) {
    const [key, ...value] = part.trim().split("=");
    if (key === name) return value.join("=");
  }
  return undefined;
}

function normalizedSource(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const realIp = request.headers.get("x-real-ip")?.trim();
  const source = (forwarded || realIp || "local-unknown").toLowerCase();
  return createHash("sha256").update(source.slice(0, 256)).digest("hex");
}

function pruneThrottle(now: number): void {
  for (const [key, value] of attempts) {
    if (value.expiresAt <= now) attempts.delete(key);
  }
  while (attempts.size >= THROTTLE_MAX_KEYS) {
    const oldest = attempts.keys().next().value as string | undefined;
    if (!oldest) break;
    attempts.delete(oldest);
  }
}

export function signInAllowed(request: Request, now = Date.now()): boolean {
  pruneThrottle(now);
  const entry = attempts.get(normalizedSource(request));
  return !entry || entry.expiresAt <= now || entry.failures < THROTTLE_MAX_FAILURES;
}

export function recordFailedSignIn(request: Request, now = Date.now()): void {
  pruneThrottle(now);
  const key = normalizedSource(request);
  const current = attempts.get(key);
  attempts.delete(key);
  attempts.set(key, current && current.expiresAt > now
    ? { failures: current.failures + 1, expiresAt: current.expiresAt }
    : { failures: 1, expiresAt: now + THROTTLE_WINDOW_MS });
}

export function clearSignInFailures(request: Request): void {
  attempts.delete(normalizedSource(request));
}

export async function currentSession(request: Request): Promise<SuperUserSession | null> {
  return verifySessionToken(cookieValue(request, sessionCookieName()));
}

export function assertSameOrigin(request: Request): void {
  const origin = request.headers.get("origin");
  let expected: string;
  try {
    const requestUrl = new URL(request.url);
    const host = request.headers.get("host") ?? requestUrl.host;
    const forwardedProtocol = request.headers.get("x-forwarded-proto")?.split(",")[0]?.trim();
    const protocol = forwardedProtocol === "http" || forwardedProtocol === "https"
      ? `${forwardedProtocol}:`
      : requestUrl.protocol;
    expected = `${protocol}//${host}`;
  } catch {
    throw new RuntimePublicError("invalid_request_origin", "validation", "The request origin is invalid.", 403);
  }
  if (!origin || origin !== expected) {
    throw new RuntimePublicError("cross_origin_request_forbidden", "validation", "The mutation request origin is not allowed.", 403);
  }
}

export async function requireSuperUser(request: Request): Promise<SuperUserSession> {
  const session = await currentSession(request);
  if (!session) {
    throw new RuntimePublicError("authentication_required", "validation", "Authentication is required.", 401);
  }
  return session;
}

export async function requireSuperUserMutation(request: Request): Promise<SuperUserSession> {
  const session = await requireSuperUser(request);
  assertSameOrigin(request);
  return session;
}

export function trustedServiceCredential(provided: string, configured: string): boolean {
  if (configured.length < 16) return false;
  const left = createHash("sha256").update(provided).digest();
  const right = createHash("sha256").update(configured).digest();
  return timingSafeEqual(left, right);
}

export async function authorizeSuperUserOrService(
  request: Request,
  serviceEnabled: boolean,
  suppliedServiceCredential: string,
  configuredServiceCredential: string,
): Promise<{ authority: "super_user"; session: SuperUserSession } | { authority: "trusted_service" }> {
  if (serviceEnabled && trustedServiceCredential(suppliedServiceCredential, configuredServiceCredential)) {
    return { authority: "trusted_service" };
  }
  return { authority: "super_user", session: await requireSuperUserMutation(request) };
}
