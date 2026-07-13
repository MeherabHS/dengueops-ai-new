import { createHash, randomUUID, timingSafeEqual } from "node:crypto";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import type { DecisionResponse } from "@/lib/runtime/contracts";
import { readVerifiedDecision } from "@/lib/runtime/decision-store";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";
import { modelLabel } from "@/lib/status-labels";
export const runtime = "nodejs";
function authorized(request: Request, configured: string) {
  const provided =
    request.headers.get("x-dengueops-internal-decision-secret") ?? "";
  return (
    configured.length >= 16 &&
    timingSafeEqual(
      createHash("sha256").update(configured).digest(),
      createHash("sha256").update(provided).digest(),
    )
  );
}
export async function GET(
  request: Request,
  context: { params: Promise<{ decisionId: string }> },
) {
  const correlationId = randomUUID();
  try {
    const config = loadRuntimeConfig(false);
    if (
      !config.internalDecisionEnabled ||
      !config.internalDecisionSecret ||
      !config.internalOperatorId
    ) {
      throw new RuntimePublicError(
        "internal_decision_disabled",
        "configuration",
        "Trusted internal model decisions are disabled.",
        503,
      );
    }
    if (!authorized(request, config.internalDecisionSecret)) {
      throw new RuntimePublicError(
        "internal_decision_forbidden",
        "validation",
        "Trusted internal model decision access is forbidden.",
        403,
      );
    }
    const { decisionId } = await context.params;
    const value = await readVerifiedDecision(config, decisionId);
    const d = value.decision;
    const response: DecisionResponse = {
      ok: true,
      decisionId: d.decisionId,
      assessmentId: d.assessmentId,
      decision: d.decision,
      selectedModelId: d.selectedModelId,
      selectedModelLabel: d.selectedModelId
        ? modelLabel(d.selectedModelId)
        : null,
      decisionScope: "one_run",
      operatorType: "trusted_internal_unverified",
      institutionalApproval: false,
      reason: d.reason,
      decisionStatus: d.decisionStatus,
      forecastAuthorized: d.forecastAuthorized,
      authorizationId: d.authorizationId,
      authorizationStatus: value.authorizationStatus,
      createdAt: d.createdAt,
      limitations: [
        "Recommendation strength is not available.",
        "This is not institutional approval or deployment-wide adoption.",
      ],
      decisionCommitSha256: value.decisionCommitSha256,
    };
    return Response.json(response, {
      headers: { "Cache-Control": "no-store" },
    });
  } catch (error) {
    const failure = errorResponse(error, correlationId);
    return Response.json(failure.body, {
      status: failure.status,
      headers: { "Cache-Control": "no-store" },
    });
  }
}
