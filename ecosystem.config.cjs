/* eslint-disable @typescript-eslint/no-require-imports */
const path = require("node:path");

function requiredAbsoluteLinuxPath(name) {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required for the production PM2 configuration.`);
  if (!path.posix.isAbsolute(value)) throw new Error(`${name} must be an absolute Linux path.`);
  return value;
}

const pythonExecutable = requiredAbsoluteLinuxPath("DENGUEOPS_PYTHON_EXECUTABLE");
const runtimeRoot = requiredAbsoluteLinuxPath("DENGUEOPS_RUNTIME_ROOT");
const communityUploadRoot = requiredAbsoluteLinuxPath("DENGUEOPS_COMMUNITY_UPLOAD_ROOT");
const configuredPort = Number(process.env.DENGUEOPS_WEB_PORT || 3000);
if (!Number.isSafeInteger(configuredPort) || configuredPort < 1024 || configuredPort > 65535) {
  throw new Error("DENGUEOPS_WEB_PORT must be an unprivileged TCP port.");
}

const sharedRuntimeEnvironment = {
  DENGUEOPS_PYTHON_EXECUTABLE: pythonExecutable,
  DENGUEOPS_RUNTIME_ROOT: runtimeRoot,
  PYTHONDONTWRITEBYTECODE: "1",
};

const supervision = {
  cwd: __dirname,
  instances: 1,
  exec_mode: "fork",
  autorestart: true,
  watch: false,
  restart_delay: 5000,
  max_restarts: 10,
  min_uptime: "10s",
  kill_timeout: 15000,
  time: true,
};

module.exports = {
  apps: [
    {
      ...supervision,
      name: "dengueops-web",
      script: "node_modules/next/dist/bin/next",
      args: `start -H 127.0.0.1 -p ${configuredPort}`,
      env: {
        NODE_ENV: "production",
        HOSTNAME: "127.0.0.1",
        PORT: String(configuredPort),
        DENGUEOPS_COMMUNITY_UPLOAD_ROOT: communityUploadRoot,
        ...sharedRuntimeEnvironment,
      },
    },
    {
      ...supervision,
      name: "dengueops-runtime-worker",
      script: "scripts/runtime-worker.mjs",
      interpreter: "node",
      env: {
        NODE_ENV: "production",
        ...sharedRuntimeEnvironment,
      },
    },
  ],
};
