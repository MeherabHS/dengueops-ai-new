import assert from "node:assert/strict";
import { createHmac, randomBytes, scryptSync } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const username = "test-super-user";
const password = "test-only-password-value";
const sessionSecret = randomBytes(48).toString("base64url");

function passwordHash() {
  const salt = randomBytes(16);
  const digest = scryptSync(password, salt, 32, { N: 16384, r: 8, p: 1, maxmem: 64 * 1024 * 1024 });
  return `scrypt$16384$8$1$${salt.toString("base64url")}$${digest.toString("base64url")}`;
}

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      server.close(() => resolve(address.port));
    });
  });
}

async function startServer(configured = true) {
  const runtime = await mkdtemp(path.join(tmpdir(), "dengueops-b92-auth-"));
  const port = await freePort();
  const child = spawn(process.execPath, [path.join(root, "node_modules/next/dist/bin/next"), "dev", "-H", "127.0.0.1", "-p", String(port)], {
    cwd: root,
    env: {
      ...process.env,
      DENGUEOPS_RUNTIME_ROOT: runtime,
      DENGUEOPS_PYTHON_EXECUTABLE: process.execPath,
      DENGUEOPS_SUPER_USER_USERNAME: configured ? username : "",
      DENGUEOPS_SUPER_USER_PASSWORD_HASH: configured ? passwordHash() : "",
      DENGUEOPS_SESSION_SECRET: configured ? sessionSecret : "",
      DENGUEOPS_INTERNAL_DECISION_ENABLED: "false",
      DENGUEOPS_INTERNAL_MONITORING_ENABLED: "false",
      DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_ENABLED: "false",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  child.stdout.on("data", (value) => { logs += value; });
  child.stderr.on("data", (value) => { logs += value; });
  const url = `http://127.0.0.1:${port}`;
  for (let count = 0; count < 150; count += 1) {
    try {
      const response = await fetch(`${url}/dashboard`);
      if (response.ok) return { child, runtime, url, logs: () => logs };
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  child.kill();
  throw new Error(logs);
}

async function stopServer(instance) {
  instance.child.kill();
  await rm(instance.runtime, { recursive: true, force: true });
}

async function signIn(instance, suppliedUsername = username, suppliedPassword = password) {
  return fetch(`${instance.url}/api/auth/sign-in`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username: suppliedUsername, password: suppliedPassword }),
  });
}

function signedToken(payload) {
  const encoded = Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature = createHmac("sha256", sessionSecret).update(encoded).digest("base64url");
  return `${encoded}.${signature}`;
}

test("configured credentials issue only a bounded signed super_user session", { timeout: 60_000 }, async () => {
  const instance = await startServer();
  try {
    const response = await signIn(instance);
    assert.equal(response.status, 200);
    const cookie = response.headers.get("set-cookie");
    assert.match(cookie, /^dengueops_session=/);
    assert.match(cookie, /HttpOnly/i);
    assert.match(cookie, /SameSite=Strict/i);
    assert.match(cookie, /Path=\//i);
    assert.match(cookie, /Max-Age=28800/i);
    assert.equal(cookie.includes(password), false);
    const current = await fetch(`${instance.url}/api/auth/sign-in`, { headers: { cookie } });
    assert.deepEqual(await current.json(), { authenticated: true, role: "super_user" });
  } finally {
    await stopServer(instance);
  }
});

test("invalid and missing credential configurations fail closed without identity disclosure", { timeout: 90_000 }, async () => {
  const configured = await startServer();
  try {
    for (const [badUsername, badPassword] of [["wrong", password], [username, "wrong"]]) {
      const response = await signIn(configured, badUsername, badPassword);
      assert.equal(response.status, 401);
      assert.deepEqual(await response.json(), { ok: false, error: "Invalid username or password." });
    }
    for (let count = 0; count < 4; count += 1) {
      const response = await signIn(configured, "wrong", "wrong");
      assert.equal(response.status, 401);
      assert.deepEqual(await response.json(), { ok: false, error: "Invalid username or password." });
    }
  } finally {
    await stopServer(configured);
  }
  const missing = await startServer(false);
  try {
    const response = await signIn(missing);
    assert.equal(response.status, 503);
    assert.deepEqual(await response.json(), { ok: false, error: "Authentication is unavailable." });
  } finally {
    await stopServer(missing);
  }
});

test("tampered, expired, and non-super-user sessions fail closed; sign-out clears the cookie", { timeout: 60_000 }, async () => {
  const instance = await startServer();
  try {
    const login = await signIn(instance);
    const cookie = login.headers.get("set-cookie");
    const validToken = cookie.match(/^dengueops_session=([^;]+)/)[1];
    const tampered = `${validToken.slice(0, -1)}${validToken.endsWith("A") ? "B" : "A"}`;
    const now = Math.floor(Date.now() / 1000);
    const expired = signedToken({ sub: username, role: "super_user", iat: now - 28801, exp: now - 1, v: 1 });
    const elevated = signedToken({ sub: username, role: "administrator", iat: now, exp: now + 28800, v: 1 });
    for (const token of [tampered, expired, elevated]) {
      const response = await fetch(`${instance.url}/api/auth/sign-in`, { headers: { cookie: `dengueops_session=${token}` } });
      assert.deepEqual(await response.json(), { authenticated: false, role: null });
    }
    const signOut = await fetch(`${instance.url}/api/auth/sign-out`, {
      method: "POST",
      headers: { cookie, origin: instance.url },
    });
    assert.equal(signOut.status, 200);
    assert.match(signOut.headers.get("set-cookie"), /Max-Age=0/i);
  } finally {
    await stopServer(instance);
  }
});
