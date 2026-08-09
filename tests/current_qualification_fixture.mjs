import { execFileSync } from "node:child_process";
import { cp, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { findPython } from "./node_python_runner.mjs";

export async function copyRuntimeWithCurrentQualifications(repositoryRoot, prefix) {
  const runtimeRoot = await mkdtemp(path.join(os.tmpdir(), prefix));
  await cp(path.join(repositoryRoot, "runtime"), runtimeRoot, { recursive: true });
  const script = [
    "import sys",
    "from pathlib import Path",
    "sys.path.insert(0, str(Path.cwd() / 'analytics'))",
    "from runtime_hospital_preparedness_commit import publish_qualification",
    "root = Path(sys.argv[1]).resolve()",
    "[publish_qualification(root, scenario) for scenario in ('baseline_availability', 'constrained_availability', 'severe_constraint')]",
  ].join(";");
  execFileSync(findPython().command, ["-c", script, runtimeRoot], {
    cwd: repositoryRoot,
    env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
    encoding: "utf8",
    windowsHide: true,
  });
  return runtimeRoot;
}
