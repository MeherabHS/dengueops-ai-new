import { parseScenario, readPublicDashboard } from "@/lib/community/public-read-model";
import { RuntimePublicError } from "@/lib/runtime/errors";

const headers = { "Cache-Control": "no-store" };

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const scenarioValues = url.searchParams.getAll("scenario");
    if (scenarioValues.length > 1) throw new RuntimePublicError("unsupported_scenario", "validation", "The availability scenario is unsupported.", 400);
    const dashboard = await readPublicDashboard(parseScenario(scenarioValues[0] ?? null));
    return Response.json({
      schemaVersion: dashboard.schemaVersion,
      area: dashboard.area,
      forecast: dashboard.forecast,
      preparedness: dashboard.preparedness,
      qualificationPreparedness: dashboard.qualificationPreparedness,
      freshness: dashboard.freshness,
      evidence: dashboard.evidence,
    }, { headers });
  } catch (error) {
    const unsupported = error instanceof RuntimePublicError && error.code === "unsupported_scenario";
    return Response.json(
      { error: { code: unsupported ? "unsupported_scenario" : "current_hospital_readiness_unavailable", message: unsupported ? "The availability scenario is unsupported." : "Current verified hospital readiness information is unavailable." } },
      { status: unsupported ? 400 : 503, headers },
    );
  }
}
