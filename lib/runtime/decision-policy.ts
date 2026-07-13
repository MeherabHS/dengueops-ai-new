import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { RuntimePublicError } from "./errors";

export interface RuntimeDecisionPolicy {
  schemaVersion: "1.0"; policyId: "RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION"; policyVersion: "p1.4d-3-e-v1";
  policyStatus: "active" | "inactive" | "suspended"; policySha256: string; deploymentId: "dhaka_south";
  allowedAssessmentPolicyId: string; allowedAssessmentPolicyVersion: string; allowedAssessmentPolicySha256: string;
  candidateRegistrySha256: string; decisionScope: "one_run"; recommendationStatusAccepted: "evidence_only";
  recommendationStrengthAccepted: "not_available"; allowedDecisions: string[]; allowedDeployableCandidateClasses: ["deployable_learned_model"];
  currentModelId: "random_forest"; currentModelParameterSha256: string; baselineApprovalAllowed: false;
  deploymentWideAdoptionAllowed: false; institutionalApproval: false; operatorType: "trusted_internal_unverified";
  assessmentValiditySeconds: number; authorizationPolicy: Record<string, unknown>; limitations: string[]; prohibitedClaims: string[];
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return `{${Object.entries(value as Record<string, unknown>).sort(([a],[b]) => a.localeCompare(b)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`;
  return JSON.stringify(value);
}

export async function loadDecisionPolicy(repositoryRoot: string, deploymentId: string): Promise<RuntimeDecisionPolicy> {
  if (deploymentId !== "dhaka_south") throw new RuntimePublicError("decision_deployment_not_allowed", "validation", "The deployment is not authorized for internal model decisions.", 403);
  const file = path.join(repositoryRoot, "config", "deployments", deploymentId, "decision_policy.json");
  const policy = JSON.parse(await readFile(file, "utf8")) as RuntimeDecisionPolicy;
  const withoutHash = { ...policy } as Record<string, unknown>; delete withoutHash.policySha256;
  const digest = createHash("sha256").update(canonical(withoutHash), "utf8").digest("hex");
  if (policy.policySha256 !== digest || policy.policyStatus !== "active" || policy.policyId !== "RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION" || policy.policyVersion !== "p1.4d-3-e-v1" || policy.decisionScope !== "one_run" || policy.baselineApprovalAllowed || policy.deploymentWideAdoptionAllowed || policy.institutionalApproval) {
    throw new RuntimePublicError("decision_policy_invalid", "configuration", "The governed internal decision policy is unavailable or invalid.", 503);
  }
  return policy;
}
