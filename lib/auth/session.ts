const SESSION_COOKIE_NAME = "dengueops_session";
const SESSION_VERSION = 1;
const SESSION_DURATION_SECONDS = 8 * 60 * 60;
const MINIMUM_SECRET_LENGTH = 32;

export interface SuperUserSession {
  sub: string;
  role: "super_user";
  iat: number;
  exp: number;
  v: 1;
}

function configuredSecret(): Uint8Array {
  const secret = process.env.DENGUEOPS_SESSION_SECRET ?? "";
  if (secret.length < MINIMUM_SECRET_LENGTH) {
    throw new Error("session_configuration_unavailable");
  }
  return new TextEncoder().encode(secret);
}

function encodeBase64Url(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString("base64url");
}

function decodeBase64Url(value: string): Uint8Array {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error("invalid_session_encoding");
  return new Uint8Array(Buffer.from(value, "base64url"));
}

async function sign(value: string): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    "raw",
    configuredSecret().slice().buffer as ArrayBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value).buffer as ArrayBuffer));
}

async function signatureMatches(value: string, supplied: Uint8Array): Promise<boolean> {
  const expected = await sign(value);
  if (expected.length !== supplied.length) return false;
  let difference = 0;
  for (let index = 0; index < expected.length; index += 1) {
    difference |= expected[index] ^ supplied[index];
  }
  return difference === 0;
}

export async function createSessionToken(
  subject: string,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<string> {
  const normalizedSubject = subject.trim();
  if (!normalizedSubject || normalizedSubject.length > 128) {
    throw new Error("invalid_session_subject");
  }
  const payload: SuperUserSession = {
    sub: normalizedSubject,
    role: "super_user",
    iat: nowSeconds,
    exp: nowSeconds + SESSION_DURATION_SECONDS,
    v: SESSION_VERSION,
  };
  const encodedPayload = encodeBase64Url(new TextEncoder().encode(JSON.stringify(payload)));
  return `${encodedPayload}.${encodeBase64Url(await sign(encodedPayload))}`;
}

export async function verifySessionToken(
  token: string | undefined,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<SuperUserSession | null> {
  try {
    if (!token || token.length > 2048) return null;
    const parts = token.split(".");
    if (parts.length !== 2) return null;
    const [encodedPayload, encodedSignature] = parts;
    if (!(await signatureMatches(encodedPayload, decodeBase64Url(encodedSignature)))) return null;
    const value = JSON.parse(new TextDecoder().decode(decodeBase64Url(encodedPayload))) as Record<string, unknown>;
    const keys = Object.keys(value).sort().join("|");
    if (keys !== "exp|iat|role|sub|v"
      || value.v !== SESSION_VERSION
      || value.role !== "super_user"
      || typeof value.sub !== "string"
      || !value.sub
      || value.sub.length > 128
      || !Number.isSafeInteger(value.iat)
      || !Number.isSafeInteger(value.exp)
      || Number(value.iat) > nowSeconds + 60
      || Number(value.exp) <= nowSeconds
      || Number(value.exp) - Number(value.iat) !== SESSION_DURATION_SECONDS) {
      return null;
    }
    return value as unknown as SuperUserSession;
  } catch {
    return null;
  }
}

export function sessionCookieName(): string {
  return SESSION_COOKIE_NAME;
}

export function sessionCookie(token: string): string {
  return [
    `${SESSION_COOKIE_NAME}=${token}`,
    "HttpOnly",
    "SameSite=Strict",
    process.env.NODE_ENV === "production" ? "Secure" : "",
    "Path=/",
    `Max-Age=${SESSION_DURATION_SECONDS}`,
  ].filter(Boolean).join("; ");
}

export function clearedSessionCookie(): string {
  return [
    `${SESSION_COOKIE_NAME}=`,
    "HttpOnly",
    "SameSite=Strict",
    process.env.NODE_ENV === "production" ? "Secure" : "",
    "Path=/",
    "Max-Age=0",
  ].filter(Boolean).join("; ");
}
