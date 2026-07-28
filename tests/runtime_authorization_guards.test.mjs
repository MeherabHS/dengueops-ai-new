import assert from "node:assert/strict";
import { randomBytes, scryptSync } from "node:crypto";
import { mkdtemp, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import test from "node:test";

const root = path.resolve(import.meta.dirname, "..");
const username = "guard-test-super-user";
const password = "guard-test-password-value";
const serviceSecret = "guard-test-service-secret-value";

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

async function startServer() {
  const runtime = await mkdtemp(path.join(tmpdir(), "dengueops-b92-guards-"));
  const port = await freePort();
  const child = spawn(process.execPath, [path.join(root, "node_modules/next/dist/bin/next"), "dev", "-H", "127.0.0.1", "-p", String(port)], {
    cwd: root,
    env: {
      ...process.env,
      DENGUEOPS_RUNTIME_ROOT: runtime,
      DENGUEOPS_PYTHON_EXECUTABLE: process.execPath,
      DENGUEOPS_SUPER_USER_USERNAME: username,
      DENGUEOPS_SUPER_USER_PASSWORD_HASH: passwordHash(),
      DENGUEOPS_SESSION_SECRET: randomBytes(48).toString("base64url"),
      DENGUEOPS_INTERNAL_DECISION_ENABLED: "true",
      DENGUEOPS_INTERNAL_DECISION_SECRET: serviceSecret,
      DENGUEOPS_INTERNAL_OPERATOR_ID: "guard-service-operator",
      DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_ENABLED: "true",
      DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_SECRET: "guard-lifecycle-secret-value",
      DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_OPERATOR_ID: "guard-lifecycle-operator",
      DENGUEOPS_INTERNAL_MONITORING_ENABLED: "false",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let logs = "";
  child.stdout.on("data", (value) => { logs += value; });
  child.stderr.on("data", (value) => { logs += value; });
  const url = `http://127.0.0.1:${port}`;
  for (let count = 0; count < 150; count += 1) {
    try {
      if ((await fetch(`${url}/dashboard`)).ok) return { child, runtime, url, logs: () => logs };
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

async function cookieFor(instance) {
  const response = await fetch(`${instance.url}/api/auth/sign-in`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  assert.equal(response.status, 200);
  return response.headers.get("set-cookie");
}

const posts = [
  ["/api/runtime/validate", "text/plain", "not multipart"],
  ["/api/runtime/assessments", "application/json", "{}"],
  ["/api/runtime/assessments/00000000-0000-4000-8000-000000000000/decisions", "application/json", "{}"],
  ["/api/runtime/decisions/00000000-0000-4000-8000-000000000000/forecast", "application/json", "{}"],
  ["/api/runtime/runs/quick", "application/json", "{}"],
];

test("all browser mutation routes reject anonymous work before durable activity", { timeout: 90_000 }, async () => {
  const instance = await startServer();
  try {
    assert.deepEqual(await readdir(instance.runtime), []);
    for (const [route, contentType, body] of posts) {
      const response = await fetch(`${instance.url}${route}`, {
        method: "POST",
        headers: { "content-type": contentType },
        body,
      });
      assert.equal(response.status, 401, route);
    }
    assert.deepEqual(await readdir(instance.runtime), []);
  } finally {
    await stopServer(instance);
  }
});

test("valid session reaches existing validation boundaries and cross-origin session use fails", { timeout: 90_000 }, async () => {
  const instance = await startServer();
  try {
    const cookie = await cookieFor(instance);
    for (const [route, contentType, body] of posts) {
      const response = await fetch(`${instance.url}${route}`, {
        method: "POST",
        headers: { cookie, origin: instance.url, "content-type": contentType },
        body,
      });
      assert.notEqual(response.status, 401, route);
      assert.notEqual(response.status, 403, route);
    }
    const crossOrigin = await fetch(`${instance.url}/api/runtime/runs/quick`, {
      method: "POST",
      headers: { cookie, origin: "https://attacker.invalid", "content-type": "application/json" },
      body: "{}",
    });
    assert.equal(crossOrigin.status, 403);
  } finally {
    await stopServer(instance);
  }
});

test("trusted decision service remains compatible and historical lifecycle rejects browser sessions", { timeout: 90_000 }, async () => {
  const instance = await startServer();
  try {
    const service = await fetch(`${instance.url}/api/runtime/assessments/00000000-0000-4000-8000-000000000000/decisions`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-dengueops-internal-decision-secret": serviceSecret },
      body: "{}",
    });
    assert.notEqual(service.status, 401);
    assert.notEqual(service.status, 403);
    const forecastService = await fetch(`${instance.url}/api/runtime/decisions/00000000-0000-4000-8000-000000000000/forecast`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-dengueops-internal-decision-secret": serviceSecret },
      body: "{}",
    });
    assert.notEqual(forecastService.status, 401);
    assert.notEqual(forecastService.status, 403);
    const cookie = await cookieFor(instance);
    const lifecycle = await fetch(`${instance.url}/api/runtime/model-lifecycle`, {
      method: "POST",
      headers: { cookie, origin: instance.url, "content-type": "application/json" },
      body: "{}",
    });
    assert.equal(lifecycle.status, 401);
  } finally {
    await stopServer(instance);
  }
});

test("public pages remain public while protected pages redirect anonymous browsers", { timeout: 90_000 }, async () => {
  const instance = await startServer();
  try {
    for (const route of ["/dashboard", "/preparedness"]) {
      assert.equal((await fetch(`${instance.url}${route}`)).status, 200);
    }
    for (const route of ["/forecast", "/validation"]) {
      const response = await fetch(`${instance.url}${route}`, { redirect: "manual" });
      assert.equal(response.status, 307);
      assert.match(response.headers.get("location"), /\/sign-in\?next=/);
    }
  } finally {
    await stopServer(instance);
  }
});
