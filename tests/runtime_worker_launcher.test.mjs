import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import {
  launchRuntimeWorker,
  resolvePythonExecutable,
  resolveWorkerLaunch,
} from "../scripts/runtime-worker.mjs";

const configured = "C:\\Users\\CUBE\\AppData\\Local\\Programs\\Python\\Python313\\python.exe";

test("configured Python remains one exact spawn executable, including paths with spaces", () => {
  const spaced = "C:\\Program Files\\DengueOps Python\\python.exe";
  assert.equal(resolvePythonExecutable({ DENGUEOPS_PYTHON_EXECUTABLE: `  ${configured}  ` }), configured);
  const launch = resolveWorkerLaunch({ DENGUEOPS_PYTHON_EXECUTABLE: spaced });
  assert.equal(launch.executable, spaced);
  assert.equal(launch.args.length, 1);
  assert.equal(launch.args[0], path.join(process.cwd(), "analytics", "runtime_worker.py"));
  assert.equal(launch.options.cwd, process.cwd());
  assert.equal(launch.options.stdio, "inherit");
  assert.equal(launch.options.shell, false);
});

test("missing, blank, and relative Python configuration fail closed without PATH fallback", async () => {
  for (const env of [{}, { DENGUEOPS_PYTHON_EXECUTABLE: "   " }, { DENGUEOPS_PYTHON_EXECUTABLE: "python" }]) {
    assert.throws(() => resolvePythonExecutable(env), /not configured|absolute path/);
  }
  const source = await readFile(new URL("../scripts/runtime-worker.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(source, /\|\|\s*["'](?:python|python3|py)["']/);
});

test("launcher uses shell-free inherited stdio and propagates worker exit code", () => {
  const child = new EventEmitter();
  let observed;
  let exitCode = null;
  const result = launchRuntimeWorker({
    env: { DENGUEOPS_PYTHON_EXECUTABLE: configured },
    spawnImpl: (executable, args, options) => {
      observed = { executable, args, options };
      return child;
    },
    setExitCode: (code) => {
      exitCode = code;
    },
  });
  assert.equal(result, child);
  assert.equal(observed.executable, configured);
  assert.deepEqual(observed.args, [path.join(process.cwd(), "analytics", "runtime_worker.py")]);
  assert.equal(observed.options.shell, false);
  assert.equal(observed.options.stdio, "inherit");
  child.emit("exit", 7, null);
  assert.equal(exitCode, 7);
});

test("package runtime worker command uses the bounded Node launcher", async () => {
  const packageJson = JSON.parse(await readFile(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(packageJson.scripts["runtime:worker"], "node scripts/runtime-worker.mjs");
});
