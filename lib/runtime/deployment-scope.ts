import "server-only";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { RuntimePublicError } from "./errors";

export interface DeploymentProductScope {
  schemaVersion: "1.0";
  internalDeploymentId: "dhaka_south";
  deploymentDisplayName: "Dhaka";
  forecastDataCoverage: "synthetic_benchmark_dhaka_south_only";
  evidenceScope: "synthetic_qualification";
  operationalDhakaValidation: false;
}

const keys = [
  "deploymentDisplayName",
  "evidenceScope",
  "forecastDataCoverage",
  "internalDeploymentId",
  "operationalDhakaValidation",
  "schemaVersion",
].sort();

export function validateDeploymentProductScope(value: unknown): DeploymentProductScope {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new RuntimePublicError("invalid_product_scope", "configuration", "The product scope authority is invalid.", 500);
  }
  const scope = value as Record<string, unknown>;
  if (
    Object.keys(scope).sort().join("|") !== keys.join("|")
    || scope.schemaVersion !== "1.0"
    || scope.internalDeploymentId !== "dhaka_south"
    || scope.deploymentDisplayName !== "Dhaka"
    || scope.forecastDataCoverage !== "synthetic_benchmark_dhaka_south_only"
    || scope.evidenceScope !== "synthetic_qualification"
    || scope.operationalDhakaValidation !== false
  ) {
    throw new RuntimePublicError("invalid_product_scope", "configuration", "The product scope authority is invalid.", 500);
  }
  return scope as unknown as DeploymentProductScope;
}

export async function loadDeploymentProductScope(
  repositoryRoot: string,
  deploymentId = "dhaka_south",
): Promise<DeploymentProductScope> {
  if (deploymentId !== "dhaka_south") {
    throw new RuntimePublicError("unsupported_product_scope", "configuration", "The product scope is unavailable.", 404);
  }
  const scopePath = path.join(repositoryRoot, "config", "deployments", deploymentId, "product_scope.json");
  try {
    return validateDeploymentProductScope(JSON.parse(await readFile(scopePath, "utf8")));
  } catch (error) {
    if (error instanceof RuntimePublicError) throw error;
    throw new RuntimePublicError("invalid_product_scope", "configuration", "The product scope authority is unreadable.", 500);
  }
}
