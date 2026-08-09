import { spawnSync } from "node:child_process";

const PROBE = [
  "import sys",
  "sys.path.insert(0, 'analytics')",
  "import jsonschema, sklearn",
  "import runtime_active_model",
  "from tests.lifecycle_fixtures import build_one_run_chain_p2_v2",
  "print(sys.executable)",
].join("; ");

let selected;

function candidates() {
  const values = [];
  if (process.env.PYTHON?.trim()) values.push({ command: process.env.PYTHON.trim(), prefix: [] });
  if (process.platform === "win32") {
    values.push({ command: "py", prefix: ["-3.13"] });
    values.push({ command: "py", prefix: ["-3"] });
  }
  values.push({ command: "python3", prefix: [] }, { command: "python", prefix: [] });
  return values;
}

export function findPython() {
  if (selected) return selected;
  const failures = [];
  for (const candidate of candidates()) {
    const result = spawnSync(candidate.command, [...candidate.prefix, "-c", PROBE], {
      cwd: process.cwd(),
      env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
      encoding: "utf8",
      timeout: 30_000,
      windowsHide: true,
    });
    if (result.status === 0) {
      const executable = result.stdout.trim().split(/\r?\n/).at(-1);
      selected = { command: executable, prefix: [] };
      return selected;
    }
    failures.push(`${candidate.command} ${candidate.prefix.join(" ")}: ${result.error?.message ?? result.stderr.trim() ?? `exit ${result.status}`}`);
  }
  throw new Error(`No Python interpreter can import the active-model parity runtime.\n${failures.join("\n")}`);
}

export function spawnPythonSync(args, options = {}) {
  const python = findPython();
  return spawnSync(python.command, [...python.prefix, ...args], {
    cwd: process.cwd(),
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", ...options.env },
    encoding: "utf8",
    windowsHide: true,
    ...options,
  });
}
