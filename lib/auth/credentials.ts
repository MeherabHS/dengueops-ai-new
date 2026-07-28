import "server-only";

import { scrypt, timingSafeEqual } from "node:crypto";
const PASSWORD_HASH = /^scrypt\$(\d+)\$(\d+)\$(\d+)\$([A-Za-z0-9_-]+)\$([A-Za-z0-9_-]+)$/;
const EXPECTED_N = 16384;
const EXPECTED_R = 8;
const EXPECTED_P = 1;

function equalText(left: string, right: string): boolean {
  const leftDigest = Buffer.from(left.normalize("NFKC"), "utf8");
  const rightDigest = Buffer.from(right.normalize("NFKC"), "utf8");
  const length = Math.max(leftDigest.length, rightDigest.length, 1);
  const paddedLeft = Buffer.alloc(length);
  const paddedRight = Buffer.alloc(length);
  leftDigest.copy(paddedLeft);
  rightDigest.copy(paddedRight);
  return timingSafeEqual(paddedLeft, paddedRight) && leftDigest.length === rightDigest.length;
}

export function credentialsConfigured(): boolean {
  return Boolean(
    process.env.DENGUEOPS_SUPER_USER_USERNAME?.trim()
    && process.env.DENGUEOPS_SUPER_USER_PASSWORD_HASH?.trim()
    && (process.env.DENGUEOPS_SESSION_SECRET?.length ?? 0) >= 32,
  );
}

export async function verifyConfiguredCredentials(username: string, password: string): Promise<boolean> {
  const configuredUsername = process.env.DENGUEOPS_SUPER_USER_USERNAME?.trim() ?? "";
  const configuredHash = process.env.DENGUEOPS_SUPER_USER_PASSWORD_HASH?.trim() ?? "";
  if (!configuredUsername || !configuredHash || !password || password.length > 1024) return false;
  const match = PASSWORD_HASH.exec(configuredHash);
  if (!match) return false;
  const [, nText, rText, pText, saltText, digestText] = match;
  const n = Number(nText);
  const r = Number(rText);
  const p = Number(pText);
  if (n !== EXPECTED_N || r !== EXPECTED_R || p !== EXPECTED_P) return false;
  let salt: Buffer;
  let expected: Buffer;
  try {
    salt = Buffer.from(saltText, "base64url");
    expected = Buffer.from(digestText, "base64url");
  } catch {
    return false;
  }
  if (salt.length !== 16 || expected.length !== 32) return false;
  const derived = await new Promise<Buffer>((resolve, reject) => {
    scrypt(password, salt, expected.length, { N: n, r, p, maxmem: 64 * 1024 * 1024 }, (error, value) => {
      if (error) reject(error);
      else resolve(value);
    });
  });
  return equalText(username.trim(), configuredUsername) && timingSafeEqual(derived, expected);
}
