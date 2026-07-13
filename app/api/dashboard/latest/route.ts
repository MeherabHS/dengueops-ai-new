import { randomUUID } from "node:crypto";
import { readLatestDashboard } from "@/lib/runtime/dashboard-reader";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import { errorResponse, RuntimePublicError } from "@/lib/runtime/errors";

export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  try {
    const config = loadRuntimeConfig(false);
    const deploymentId = new URL(request.url).searchParams.get("deployment") ?? config.defaultDeploymentId;
    if (deploymentId !== config.defaultDeploymentId) throw new RuntimePublicError("unsupported_deployment", "validation", "The requested deployment is unavailable.", 400);
    const latest = await readLatestDashboard(deploymentId);
    return Response.json({ ok: true, ...latest }, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const failure = errorResponse(error, randomUUID());
    return Response.json(failure.body, { status: failure.status, headers: { "Cache-Control": "no-store" } });
  }
}
