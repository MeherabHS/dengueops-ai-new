import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

const require = createRequire(import.meta.url);

test("production PM2 config supervises exactly one web and one explicit-Python worker", () => {
  const priorPython = process.env.DENGUEOPS_PYTHON_EXECUTABLE;
  const priorRuntime = process.env.DENGUEOPS_RUNTIME_ROOT;
  const priorUploads = process.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT;
  const priorPort = process.env.DENGUEOPS_WEB_PORT;
  process.env.DENGUEOPS_PYTHON_EXECUTABLE = "/opt/dengueops/venv/bin/python";
  process.env.DENGUEOPS_RUNTIME_ROOT = "/var/lib/dengueops-ai";
  process.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT = "/var/lib/dengueops-community-uploads";
  process.env.DENGUEOPS_WEB_PORT = "3100";
  try {
    delete require.cache[require.resolve("../ecosystem.config.cjs")];
    const config = require("../ecosystem.config.cjs");
    assert.deepEqual(config.apps.map((app) => app.name), ["dengueops-web", "dengueops-runtime-worker"]);
    for (const app of config.apps) {
      assert.equal(app.instances, 1);
      assert.equal(app.exec_mode, "fork");
      assert.equal(app.autorestart, true);
      assert.equal(app.watch, false);
    }
    const [web, worker] = config.apps;
    assert.match(web.args, /^start -H 127\.0\.0\.1 -p 3100$/);
    assert.equal(web.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT, "/var/lib/dengueops-community-uploads");
    assert.equal(worker.script, "scripts/runtime-worker.mjs");
    assert.equal(worker.env.DENGUEOPS_PYTHON_EXECUTABLE, "/opt/dengueops/venv/bin/python");
    assert.equal(worker.env.DENGUEOPS_RUNTIME_ROOT, "/var/lib/dengueops-ai");
    assert.equal(worker.env.PYTHONDONTWRITEBYTECODE, "1");
  } finally {
    if (priorPython === undefined) delete process.env.DENGUEOPS_PYTHON_EXECUTABLE;
    else process.env.DENGUEOPS_PYTHON_EXECUTABLE = priorPython;
    if (priorRuntime === undefined) delete process.env.DENGUEOPS_RUNTIME_ROOT;
    else process.env.DENGUEOPS_RUNTIME_ROOT = priorRuntime;
    if (priorUploads === undefined) delete process.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT;
    else process.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT = priorUploads;
    if (priorPort === undefined) delete process.env.DENGUEOPS_WEB_PORT;
    else process.env.DENGUEOPS_WEB_PORT = priorPort;
  }
});

test("production responses configure the required security header set", async () => {
  const imported = await import("../next.config.ts");
  const config = imported.default;
  assert.equal(typeof config.headers, "function");
  const rules = await config.headers();
  const headers = new Map(rules.flatMap((rule) => rule.headers).map((header) => [header.key, header.value]));
  for (const name of ["Content-Security-Policy", "X-Content-Type-Options", "Referrer-Policy", "Permissions-Policy", "X-Frame-Options", "Strict-Transport-Security"]) {
    assert.ok(headers.has(name), `${name} is required`);
  }
  assert.match(headers.get("Content-Security-Policy"), /frame-ancestors 'none'/);
  assert.match(headers.get("Content-Security-Policy"), /object-src 'none'/);
  assert.equal(headers.get("X-Content-Type-Options"), "nosniff");
  assert.equal(headers.get("X-Frame-Options"), "DENY");
});
