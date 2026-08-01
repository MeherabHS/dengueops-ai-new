import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const CONFIGURATION_ERROR = [
  "DENGUEOPS_PYTHON_EXECUTABLE is not configured.",
  "Set it to the Python interpreter provisioned for the DengueOps runtime.",
].join(" ");

export function resolvePythonExecutable(env = process.env) {
  const executable = env.DENGUEOPS_PYTHON_EXECUTABLE?.trim();
  if (!executable) throw new Error(CONFIGURATION_ERROR);
  if (!path.isAbsolute(executable)) {
    throw new Error("DENGUEOPS_PYTHON_EXECUTABLE must be an absolute path to the provisioned DengueOps Python interpreter.");
  }
  return executable;
}

export function resolveWorkerLaunch(env = process.env, launcherUrl = import.meta.url) {
  const repositoryRoot = path.resolve(path.dirname(fileURLToPath(launcherUrl)), "..");
  return {
    executable: resolvePythonExecutable(env),
    args: [path.join(repositoryRoot, "analytics", "runtime_worker.py")],
    options: {
      cwd: repositoryRoot,
      stdio: "inherit",
      env,
      shell: false,
    },
  };
}

export function launchRuntimeWorker({
  env = process.env,
  spawnImpl = spawn,
  reportError = (message) => console.error(message),
  setExitCode = (code) => {
    process.exitCode = code;
  },
} = {}) {
  let launch;
  try {
    launch = resolveWorkerLaunch(env);
  } catch (error) {
    reportError(error instanceof Error ? error.message : CONFIGURATION_ERROR);
    setExitCode(1);
    return null;
  }

  let child;
  try {
    child = spawnImpl(launch.executable, launch.args, launch.options);
  } catch {
    reportError(`Unable to launch configured DengueOps Python executable:\n${launch.executable}`);
    setExitCode(1);
    return null;
  }
  child.once("error", () => {
    reportError(`Unable to launch configured DengueOps Python executable:\n${launch.executable}`);
    setExitCode(1);
  });
  child.once("exit", (code, signal) => {
    setExitCode(Number.isInteger(code) ? code : signal ? 1 : 0);
  });
  return child;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  launchRuntimeWorker();
}
