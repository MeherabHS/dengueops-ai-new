import path from "node:path";
import { RuntimePublicError } from "./errors";

export interface RuntimeConfig {
  repositoryRoot: string;
  runtimeRoot: string;
  pythonExecutable: string;
  maxUploadBytes: number;
  validationTimeoutMs: number;
  quickForecastTimeoutSeconds: number;
  assessmentTimeoutSeconds: number;
  approvedForecastTimeoutSeconds: number;
  workspaceMaxAgeSeconds: number;
  internalDecisionEnabled: boolean;
  internalDecisionSecret: string;
  internalOperatorId: string;
  decisionValiditySeconds: number;
  decisionReasonMaxLength: number;
  defaultDeploymentId: string;
}

function positiveInteger(value: string | undefined, fallback: number, name: string): number {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new RuntimePublicError("invalid_runtime_configuration", "configuration", `${name} must be a positive integer.`, 500);
  }
  return parsed;
}

export function loadRuntimeConfig(requirePython = true): RuntimeConfig {
  const repositoryRoot = path.normalize(process.cwd());
  if (!path.isAbsolute(repositoryRoot)) {
    throw new RuntimePublicError("invalid_repository_root", "configuration", "The repository root must be absolute.", 500);
  }
  const configuredRuntimeRoot = process.env.DENGUEOPS_RUNTIME_ROOT?.trim();
  if (configuredRuntimeRoot && !path.isAbsolute(configuredRuntimeRoot)) {
    throw new RuntimePublicError("runtime_root_must_be_absolute", "configuration", "The runtime root must be absolute.", 500);
  }
  const runtimeRoot = path.normalize(configuredRuntimeRoot || path.join(repositoryRoot, "runtime"));
  const sharedData = path.normalize(path.join(repositoryRoot, "data"));
  const relativeToSharedData = path.relative(sharedData, runtimeRoot);
  if (relativeToSharedData === "" || (!relativeToSharedData.startsWith("..") && !path.isAbsolute(relativeToSharedData))) {
    throw new RuntimePublicError(
      "unsafe_runtime_root",
      "configuration",
      "The runtime root cannot be the governed benchmark data directory.",
      500,
    );
  }
  const pythonExecutable = process.env.DENGUEOPS_PYTHON_EXECUTABLE?.trim();
  if (!pythonExecutable && requirePython) {
    throw new RuntimePublicError(
      "python_executable_not_configured",
      "configuration",
      "The runtime Python executable is not configured.",
      503,
      true,
    );
  }
  if (pythonExecutable && !path.isAbsolute(pythonExecutable)) {
    throw new RuntimePublicError(
      "python_executable_must_be_absolute",
      "configuration",
      "The runtime Python executable must be an absolute path.",
      500,
    );
  }
  return {
    repositoryRoot,
    runtimeRoot,
    pythonExecutable: pythonExecutable ?? "",
    maxUploadBytes: positiveInteger(process.env.DENGUEOPS_MAX_UPLOAD_BYTES, 10_485_760, "DENGUEOPS_MAX_UPLOAD_BYTES"),
    validationTimeoutMs: positiveInteger(process.env.DENGUEOPS_VALIDATION_TIMEOUT_MS, 60_000, "DENGUEOPS_VALIDATION_TIMEOUT_MS"),
    quickForecastTimeoutSeconds: positiveInteger(process.env.DENGUEOPS_QUICK_FORECAST_TIMEOUT_SECONDS, 600, "DENGUEOPS_QUICK_FORECAST_TIMEOUT_SECONDS"),
    assessmentTimeoutSeconds: positiveInteger(process.env.DENGUEOPS_ASSESSMENT_TIMEOUT_SECONDS, 1800, "DENGUEOPS_ASSESSMENT_TIMEOUT_SECONDS"),
    approvedForecastTimeoutSeconds: positiveInteger(process.env.DENGUEOPS_APPROVED_FORECAST_TIMEOUT_SECONDS, 600, "DENGUEOPS_APPROVED_FORECAST_TIMEOUT_SECONDS"),
    workspaceMaxAgeSeconds: positiveInteger(process.env.DENGUEOPS_WORKSPACE_MAX_AGE_SECONDS, 86_400, "DENGUEOPS_WORKSPACE_MAX_AGE_SECONDS"),
    internalDecisionEnabled: process.env.DENGUEOPS_INTERNAL_DECISION_ENABLED?.trim().toLowerCase() === "true",
    internalDecisionSecret: process.env.DENGUEOPS_INTERNAL_DECISION_SECRET?.trim() || "",
    internalOperatorId: process.env.DENGUEOPS_INTERNAL_OPERATOR_ID?.trim() || "",
    decisionValiditySeconds: positiveInteger(process.env.DENGUEOPS_DECISION_VALIDITY_SECONDS, 2_592_000, "DENGUEOPS_DECISION_VALIDITY_SECONDS"),
    decisionReasonMaxLength: positiveInteger(process.env.DENGUEOPS_DECISION_REASON_MAX_LENGTH, 1000, "DENGUEOPS_DECISION_REASON_MAX_LENGTH"),
    defaultDeploymentId: process.env.DENGUEOPS_DEFAULT_DEPLOYMENT_ID?.trim() || "dhaka_south",
  };
}
