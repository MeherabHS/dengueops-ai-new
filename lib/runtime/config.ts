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
  internalMonitoringEnabled: boolean;
  internalMonitoringSecret: string;
  internalMonitoringOperatorId: string;
  forecastOutcomeTimeoutSeconds: number;
  internalModelLifecycleEnabled: boolean;
  internalModelLifecycleSecret: string;
  internalModelLifecycleOperatorId: string;
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
  const internalMonitoringEnabled = process.env.DENGUEOPS_INTERNAL_MONITORING_ENABLED?.trim().toLowerCase() === "true";
  const internalMonitoringSecret = process.env.DENGUEOPS_INTERNAL_MONITORING_SECRET?.trim() || "";
  const internalMonitoringOperatorId = process.env.DENGUEOPS_INTERNAL_MONITORING_OPERATOR_ID?.trim() || "";
  const internalDecisionEnabled = process.env.DENGUEOPS_INTERNAL_DECISION_ENABLED?.trim().toLowerCase() === "true";
  const internalDecisionSecret = process.env.DENGUEOPS_INTERNAL_DECISION_SECRET?.trim() || "";
  const internalOperatorId = process.env.DENGUEOPS_INTERNAL_OPERATOR_ID?.trim() || "";
  const internalModelLifecycleEnabled = process.env.DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_ENABLED?.trim().toLowerCase() === "true";
  const internalModelLifecycleSecret = process.env.DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_SECRET?.trim() || "";
  const internalModelLifecycleOperatorId = process.env.DENGUEOPS_INTERNAL_MODEL_LIFECYCLE_OPERATOR_ID?.trim() || "";
  if (internalMonitoringEnabled && (internalMonitoringSecret.length < 16 || !internalMonitoringOperatorId || internalMonitoringOperatorId.length > 128)) {
    throw new RuntimePublicError("invalid_monitoring_configuration", "configuration", "Enabled outcome monitoring requires a 16-character secret and bounded operator identifier.", 503);
  }
  if (internalDecisionEnabled && (internalDecisionSecret.length < 16 || !internalOperatorId || internalOperatorId.length > 128)) {
    throw new RuntimePublicError("invalid_decision_configuration", "configuration", "Enabled internal decisions require valid server-only configuration.", 503);
  }
  if(internalModelLifecycleEnabled&&(internalModelLifecycleSecret.length<16||!internalModelLifecycleOperatorId||internalModelLifecycleOperatorId.length>128))throw new RuntimePublicError("invalid_model_lifecycle_configuration","configuration","Enabled model lifecycle ingress requires a 16-character distinct secret and bounded operator identifier.",503);
  const enabledSecrets=[...(internalDecisionEnabled?[internalDecisionSecret]:[]),...(internalMonitoringEnabled?[internalMonitoringSecret]:[]),...(internalModelLifecycleEnabled?[internalModelLifecycleSecret]:[])];
  if(new Set(enabledSecrets).size!==enabledSecrets.length)throw new RuntimePublicError("invalid_internal_action_configuration","configuration","Enabled internal actions require distinct server-only credentials.",503);
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
    internalDecisionEnabled,
    internalDecisionSecret,
    internalOperatorId,
    decisionValiditySeconds: positiveInteger(process.env.DENGUEOPS_DECISION_VALIDITY_SECONDS, 2_592_000, "DENGUEOPS_DECISION_VALIDITY_SECONDS"),
    decisionReasonMaxLength: positiveInteger(process.env.DENGUEOPS_DECISION_REASON_MAX_LENGTH, 1000, "DENGUEOPS_DECISION_REASON_MAX_LENGTH"),
    internalMonitoringEnabled,
    internalMonitoringSecret,
    internalMonitoringOperatorId,
    forecastOutcomeTimeoutSeconds: positiveInteger(process.env.DENGUEOPS_FORECAST_OUTCOME_TIMEOUT_SECONDS, 120, "DENGUEOPS_FORECAST_OUTCOME_TIMEOUT_SECONDS"),
    internalModelLifecycleEnabled,internalModelLifecycleSecret,internalModelLifecycleOperatorId,
    defaultDeploymentId: process.env.DENGUEOPS_DEFAULT_DEPLOYMENT_ID?.trim() || "dhaka_south",
  };
}
