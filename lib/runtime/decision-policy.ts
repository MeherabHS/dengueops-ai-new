import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { RuntimePublicError } from "./errors";

const POLICY_ID = "RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION" as const;
const ASSESSMENT_POLICY_ID = "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE" as const;
const DEPLOYMENT_ID = "dhaka_south" as const;
const PHASE_ONE_ASSESSMENT_SHA = "dbf9d4cc4713bbb9d114b2dab916d0f20b3004ac14b37ca663c3caecefcea0af";
const PHASE_TWO_ASSESSMENT_SHA = "04c620ebe42526a74f1fe7054e3281df36bb587b363c027a3a675a86ee70efff";
const CANDIDATE_REGISTRY_SHA = "2e627f8a368a7e92cebd4ad62139b1050c7614559affd620e9a41738fd6a25d4";

interface RuntimeDecisionPolicyCommon {
  policyId: typeof POLICY_ID;
  policyStatus: "active" | "inactive" | "suspended";
  policySha256: string;
  deploymentId: typeof DEPLOYMENT_ID;
  allowedAssessmentPolicyId: typeof ASSESSMENT_POLICY_ID;
  allowedAssessmentPolicySha256: string;
  candidateRegistrySha256: string;
  decisionScope: "one_run";
  recommendationStatusAccepted: "evidence_only";
  recommendationStrengthAccepted: "not_available";
  allowedDecisions: ["approve_technical_winner", "keep_current_model", "defer", "reject_assessment"];
  allowedDeployableCandidateClasses: ["deployable_learned_model"];
  currentModelId: "random_forest";
  currentModelParameterSha256: string;
  baselineApprovalAllowed: false;
  deploymentWideAdoptionAllowed: false;
  institutionalApproval: false;
  operatorType: "trusted_internal_unverified";
  assessmentValiditySeconds: number;
  limitations: string[];
  prohibitedClaims: string[];
}

export interface RuntimeDecisionPolicyPhaseOne extends RuntimeDecisionPolicyCommon {
  schemaVersion: "1.0";
  policyVersion: "p1.4d-3-e-v1";
  allowedAssessmentPolicyVersion: "p1.4d-1-v1";
  authorizationPolicy: {
    scope: "one_run";
    oneAuthorizationPerFinalDecision: true;
    oneRunPerAuthorization: true;
    automaticRetryAllowed: false;
    consumeAfterCommittedLatestPointer: true;
  };
}

export interface RuntimeDecisionPolicyPhaseTwo extends RuntimeDecisionPolicyCommon {
  schemaVersion: "2.0";
  policyVersion: "p2-v1";
  allowedAssessmentSchemaVersion: "2.0";
  allowedAssessmentPolicyVersion: "p2-v1";
  successfulFoldRequirement: {
    source: "committed_assessment_planned_fold_count";
    failedFolds: 0;
    reconcileAcross: ["assessment_summary", "rolling_validation", "candidate_model_comparison", "selected_candidate"];
  };
  selectedModelTrainingPolicy: {
    scope: "all_validated_labelled_rows";
    minimumLabelledRows: 157;
    selectedEvaluationWindowMayLimitTraining: false;
  };
  authorizationPolicy: {
    scope: "one_run";
    oneAuthorizationPerFinalDecision: true;
    oneRunPerAuthorization: true;
    oneReservationPerAuthorization: true;
    automaticRetryAllowed: false;
    consumeAfterCommittedLatestPointer: true;
  };
}

export type RuntimeDecisionPolicy = RuntimeDecisionPolicyPhaseOne | RuntimeDecisionPolicyPhaseTwo;

export type CommittedAssessmentPolicyIdentity =
  | { schemaVersion: "1.0"; policyId: typeof ASSESSMENT_POLICY_ID; policyVersion: "p1.4d-1-v1"; policySha256: string }
  | { schemaVersion: "2.0"; policyId: typeof ASSESSMENT_POLICY_ID; policyVersion: "p2-v1"; policySha256: string };

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

const invalid = () => new RuntimePublicError(
  "decision_policy_invalid",
  "configuration",
  "The governed internal decision policy is unavailable or invalid.",
  503,
);

function assertCommon(policy: RuntimeDecisionPolicy): void {
  if (
    policy.policyStatus !== "active" ||
    policy.policyId !== POLICY_ID ||
    policy.deploymentId !== DEPLOYMENT_ID ||
    policy.allowedAssessmentPolicyId !== ASSESSMENT_POLICY_ID ||
    policy.candidateRegistrySha256 !== CANDIDATE_REGISTRY_SHA ||
    policy.decisionScope !== "one_run" ||
    policy.recommendationStatusAccepted !== "evidence_only" ||
    policy.recommendationStrengthAccepted !== "not_available" ||
    JSON.stringify(policy.allowedDecisions) !== JSON.stringify(["approve_technical_winner", "keep_current_model", "defer", "reject_assessment"]) ||
    JSON.stringify(policy.allowedDeployableCandidateClasses) !== JSON.stringify(["deployable_learned_model"]) ||
    policy.currentModelId !== "random_forest" ||
    policy.baselineApprovalAllowed !== false ||
    policy.deploymentWideAdoptionAllowed !== false ||
    policy.institutionalApproval !== false ||
    policy.operatorType !== "trusted_internal_unverified" ||
    !Number.isSafeInteger(policy.assessmentValiditySeconds) ||
    policy.assessmentValiditySeconds < 1 ||
    policy.authorizationPolicy.scope !== "one_run" ||
    policy.authorizationPolicy.oneAuthorizationPerFinalDecision !== true ||
    policy.authorizationPolicy.oneRunPerAuthorization !== true ||
    policy.authorizationPolicy.automaticRetryAllowed !== false ||
    policy.authorizationPolicy.consumeAfterCommittedLatestPointer !== true
  ) throw invalid();
}

function hasExactKeys(value: unknown, expected: readonly string[]): boolean {
  return Boolean(value) && typeof value === "object" &&
    Object.keys(value as Record<string, unknown>).sort().join("|") === [...expected].sort().join("|");
}

export async function loadDecisionPolicy(
  repositoryRoot: string,
  deploymentId: string,
  assessment: CommittedAssessmentPolicyIdentity,
): Promise<RuntimeDecisionPolicy> {
  if (deploymentId !== DEPLOYMENT_ID || assessment.policyId !== ASSESSMENT_POLICY_ID) {
    throw new RuntimePublicError("decision_deployment_not_allowed", "validation", "The deployment or assessment policy is not authorized for internal model decisions.", 403);
  }

  let filename: string;
  if (
    assessment.schemaVersion === "1.0" &&
    assessment.policyVersion === "p1.4d-1-v1" &&
    assessment.policySha256 === PHASE_ONE_ASSESSMENT_SHA
  ) filename = "decision_policy_p1.4d-3-e-v1.json";
  else if (
    assessment.schemaVersion === "2.0" &&
    assessment.policyVersion === "p2-v1" &&
    assessment.policySha256 === PHASE_TWO_ASSESSMENT_SHA
  ) filename = "decision_policy.json";
  else throw new RuntimePublicError("decision_policy_mismatch", "validation", "The committed assessment is outside the governed decision policies.", 409);

  const file = path.join(repositoryRoot, "config", "deployments", deploymentId, filename);
  let policy: RuntimeDecisionPolicy;
  try {
    policy = JSON.parse(await readFile(file, "utf8")) as RuntimeDecisionPolicy;
  } catch {
    throw invalid();
  }
  const withoutHash = { ...policy } as Record<string, unknown>;
  delete withoutHash.policySha256;
  const digest = createHash("sha256").update(canonical(withoutHash), "utf8").digest("hex");
  if (policy.policySha256 !== digest) throw invalid();
  assertCommon(policy);

  if (assessment.schemaVersion === "1.0") {
    if (
      !hasExactKeys(policy, ["schemaVersion", "policyId", "policyVersion", "policyStatus", "policySha256", "deploymentId", "allowedAssessmentPolicyId", "allowedAssessmentPolicyVersion", "allowedAssessmentPolicySha256", "candidateRegistrySha256", "decisionScope", "recommendationStatusAccepted", "recommendationStrengthAccepted", "allowedDecisions", "allowedDeployableCandidateClasses", "currentModelId", "currentModelParameterSha256", "baselineApprovalAllowed", "deploymentWideAdoptionAllowed", "institutionalApproval", "operatorType", "assessmentValiditySeconds", "authorizationPolicy", "limitations", "prohibitedClaims"]) ||
      !hasExactKeys(policy.authorizationPolicy, ["scope", "oneAuthorizationPerFinalDecision", "oneRunPerAuthorization", "automaticRetryAllowed", "consumeAfterCommittedLatestPointer"]) ||
      policy.schemaVersion !== "1.0" ||
      policy.policyVersion !== "p1.4d-3-e-v1" ||
      policy.allowedAssessmentPolicyVersion !== "p1.4d-1-v1" ||
      policy.allowedAssessmentPolicySha256 !== PHASE_ONE_ASSESSMENT_SHA ||
      "allowedAssessmentSchemaVersion" in policy ||
      "successfulFoldRequirement" in policy ||
      "selectedModelTrainingPolicy" in policy ||
      "oneReservationPerAuthorization" in policy.authorizationPolicy
    ) throw invalid();
    return policy;
  }

  const phaseTwoPolicy = policy as RuntimeDecisionPolicyPhaseTwo;
  if (
    !hasExactKeys(policy, ["schemaVersion", "policyId", "policyVersion", "policyStatus", "policySha256", "deploymentId", "allowedAssessmentSchemaVersion", "allowedAssessmentPolicyId", "allowedAssessmentPolicyVersion", "allowedAssessmentPolicySha256", "candidateRegistrySha256", "decisionScope", "recommendationStatusAccepted", "recommendationStrengthAccepted", "allowedDecisions", "allowedDeployableCandidateClasses", "currentModelId", "currentModelParameterSha256", "baselineApprovalAllowed", "deploymentWideAdoptionAllowed", "institutionalApproval", "operatorType", "assessmentValiditySeconds", "successfulFoldRequirement", "selectedModelTrainingPolicy", "authorizationPolicy", "limitations", "prohibitedClaims"]) ||
    !hasExactKeys(phaseTwoPolicy.successfulFoldRequirement, ["source", "failedFolds", "reconcileAcross"]) ||
    !hasExactKeys(phaseTwoPolicy.selectedModelTrainingPolicy, ["scope", "minimumLabelledRows", "selectedEvaluationWindowMayLimitTraining"]) ||
    !hasExactKeys(policy.authorizationPolicy, ["scope", "oneAuthorizationPerFinalDecision", "oneRunPerAuthorization", "oneReservationPerAuthorization", "automaticRetryAllowed", "consumeAfterCommittedLatestPointer"]) ||
    policy.schemaVersion !== "2.0" ||
    policy.policyVersion !== "p2-v1" ||
    policy.allowedAssessmentSchemaVersion !== "2.0" ||
    policy.allowedAssessmentPolicyVersion !== "p2-v1" ||
    policy.allowedAssessmentPolicySha256 !== PHASE_TWO_ASSESSMENT_SHA ||
    policy.successfulFoldRequirement.source !== "committed_assessment_planned_fold_count" ||
    policy.successfulFoldRequirement.failedFolds !== 0 ||
    JSON.stringify(policy.successfulFoldRequirement.reconcileAcross) !== JSON.stringify(["assessment_summary", "rolling_validation", "candidate_model_comparison", "selected_candidate"]) ||
    policy.selectedModelTrainingPolicy.scope !== "all_validated_labelled_rows" ||
    policy.selectedModelTrainingPolicy.minimumLabelledRows !== 157 ||
    policy.selectedModelTrainingPolicy.selectedEvaluationWindowMayLimitTraining !== false ||
    policy.authorizationPolicy.oneReservationPerAuthorization !== true
  ) throw invalid();
  return policy;
}
