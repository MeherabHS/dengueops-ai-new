import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type {
  AssessmentDecisionWorkflowProjection,
  DatasetAssessmentResponse,
  DatasetAssessmentResultSuccess,
  RuntimeCandidateId,
} from "@/lib/runtime/contracts";
import { deriveAssessmentDisplayOrder } from "@/lib/runtime/assessment-ordering";
import {
  readVerifiedAssessment,
  readVerifiedAssessmentDecisionState,
} from "@/lib/runtime/decision-store";
import { loadDecisionPolicy } from "@/lib/runtime/decision-policy";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";

export const runtime = "nodejs";

export async function GET(
  _request: Request,
  context: { params: Promise<{ assessmentId: string }> },
): Promise<Response> {
  try {
    const { assessmentId } = await context.params;
    const config = loadRuntimeConfig(false);
    const evidence = await readVerifiedAssessment(config, assessmentId);
    const summary = evidence.summary as Omit<
      DatasetAssessmentResultSuccess,
      "ok" | "integrity" | "workflow"
    >;
    if (
      summary.assessmentId !== assessmentId ||
      summary.datasetId !== evidence.commit.datasetId ||
      summary.jobId !== evidence.commit.jobId ||
      summary.approvalEnabled !== false ||
      summary.adoptionStatus !== "not_adopted"
    )
      throw new RuntimePublicError(
        "assessment_integrity_error",
        "storage",
        "The assessment summary identity is invalid.",
        409,
      );

    const policy = await loadDecisionPolicy(config.repositoryRoot, summary.deploymentId);
    if (
      policy.allowedAssessmentPolicySha256 !== summary.provenance.assessmentPolicySha256 ||
      evidence.rolling.assessmentPolicy?.policyId !== policy.allowedAssessmentPolicyId ||
      evidence.rolling.assessmentPolicy?.policyVersion !== policy.allowedAssessmentPolicyVersion ||
      evidence.rolling.assessmentPolicy?.policySha256 !== policy.allowedAssessmentPolicySha256
    )
      throw new RuntimePublicError(
        "assessment_policy_mismatch",
        "storage",
        "The assessment policy identity does not match the governed decision workflow.",
        409,
      );

    const registry = JSON.parse(
      await readFile(path.join(config.repositoryRoot, "config", "candidate_models.json"), "utf8"),
    ) as { candidates: Array<{ model_id: RuntimeCandidateId; model_family: string }> };
    const families = new Map(registry.candidates.map((candidate) => [candidate.model_id, candidate.model_family]));
    const order = deriveAssessmentDisplayOrder(summary.candidates);
    const rank = new Map(
      order
        .filter((modelId) => summary.candidates.find((candidate) => candidate.modelId === modelId)?.selectionEligible)
        .map((modelId, index) => [modelId, index + 1]),
    );
    if (
      summary.technicalWinnerModelId &&
      (order[0] !== summary.technicalWinnerModelId || rank.get(summary.technicalWinnerModelId) !== 1)
    )
      throw new RuntimePublicError(
        "assessment_ordering_mismatch",
        "storage",
        "The derived candidate order does not match the committed technical winner.",
        409,
      );

    const decision = await readVerifiedAssessmentDecisionState(config, assessmentId);
    const decisionProjection: AssessmentDecisionWorkflowProjection | null = decision
      ? {
          decisionId: decision.decisionId,
          outcome: decision.outcome,
          decisionStatus: decision.decisionStatus,
          selectedModelId: decision.selectedModelId as RuntimeCandidateId | null,
          forecastAuthorized: decision.forecastAuthorized,
          authorizationId: decision.authorizationId,
          authorizationStatus: decision.authorizationStatus,
          forecastStatus: decision.committedRunId
            ? "committed"
            : decision.authorizationStatus === "reserved"
              ? "reserved"
              : decision.forecastAuthorized
                ? "authorized"
                : "not_authorized",
          committedRunId: decision.committedRunId,
          decisionCommitSha256: decision.decisionCommitSha256,
          createdAt: decision.createdAt,
        }
      : null;
    const projectedCandidates = summary.candidates
      .map((candidate) => ({
        ...candidate,
        displayRank: rank.get(candidate.modelId) ?? null,
        modelFamily: families.get(candidate.modelId) ?? candidate.modelLabel,
        technicalWinner: candidate.modelId === summary.technicalWinnerModelId,
        currentApprovedModel: candidate.modelId === policy.currentModelId,
        deployableForOneRun:
          candidate.deployabilityClass === "deployable_learned_model" &&
          candidate.selectionEligible,
      }))
      .sort((left, right) => order.indexOf(left.modelId) - order.indexOf(right.modelId));
    const winner = projectedCandidates.find((candidate) => candidate.technicalWinner) ?? null;
    const response: DatasetAssessmentResponse = {
      ok: true,
      ...summary,
      integrity: {
        assessmentSummarySha256: evidence.summarySha256,
        assessmentCommitSha256: evidence.commitSha256,
      },
      workflow: {
        assessmentId,
        assessmentPolicy: {
          policyId: policy.allowedAssessmentPolicyId,
          policyVersion: policy.allowedAssessmentPolicyVersion,
          policySha256: policy.allowedAssessmentPolicySha256,
        },
        target: "target_cases_next_2w",
        horizonWeeks: 2,
        currentApprovedModelId: policy.currentModelId,
        currentApprovedModelFamily: families.get(policy.currentModelId) ?? "RandomForestRegressor",
        candidates: projectedCandidates,
        technicalWinnerModelId: summary.technicalWinnerModelId,
        technicalWinnerDeployable: winner?.deployableForOneRun ?? false,
        recommendationStatus: summary.recommendationStatus,
        decision: decisionProjection,
      },
    };
    return Response.json(response, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error, randomUUID());
    return Response.json(failure.body, {
      status: failure.status,
      headers: { "Cache-Control": "no-store" },
    });
  }
}
