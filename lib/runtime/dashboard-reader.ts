import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { bundledOverviewViewModel, type OverviewViewModel } from "@/lib/dashboard-view-model";
import { loadRuntimeConfig } from "./config";
import { RuntimePublicError } from "./errors";
import { assertContained, deploymentRuntimePaths, runtimeCollectionPaths } from "./paths";

const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;

export async function readLatestDashboard(deploymentId: string): Promise<{ sourceType: "bundled_benchmark" | "uploaded"; runId: string; dashboard: OverviewViewModel }> {
  const config = loadRuntimeConfig(false);
  const deployment = deploymentRuntimePaths(config.runtimeRoot, deploymentId);
  let pointerBytes: Buffer;
  try { pointerBytes = await readFile(deployment.latest); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { sourceType: "bundled_benchmark", runId: bundledOverviewViewModel.latestRun.runId, dashboard: bundledOverviewViewModel };
    throw error;
  }
  try {
    const pointer = JSON.parse(pointerBytes.toString("utf8")) as Record<string, any>;
    const approved = pointer.workflowMode === "approved_assessment_forecast";
    const pointerKeys = approved ? ["schemaVersion", "deploymentId", "runId", "datasetId", "workflowMode", "sourceType", "decisionId", "assessmentId", "authorizationId", "selectedModelId", "committedAt", "modelCardSha256", "dashboardSummarySha256", "commitRecordSha256"] : ["schemaVersion", "deploymentId", "runId", "datasetId", "workflowMode", "sourceType", "committedAt", "modelCardSha256", "dashboardSummarySha256", "commitRecordSha256"];
    if (Object.keys(pointer).sort().join("|") !== [...pointerKeys].sort().join("|") || pointer.schemaVersion !== "1.0" || pointer.deploymentId !== deploymentId || !["quick_forecast","approved_assessment_forecast"].includes(String(pointer.workflowMode)) || pointer.sourceType !== "uploaded" || !UUID.test(String(pointer.runId)) || (approved && (!UUID.test(String(pointer.decisionId)) || !UUID.test(String(pointer.assessmentId)) || !UUID.test(String(pointer.authorizationId)))) || !SHA.test(String(pointer.datasetId)) || !SHA.test(String(pointer.modelCardSha256)) || !SHA.test(String(pointer.dashboardSummarySha256)) || !SHA.test(String(pointer.commitRecordSha256))) throw new Error("identity");
    const runs = runtimeCollectionPaths(config.runtimeRoot).runs;
    const runRoot = assertContained(runs, path.join(runs, String(pointer.runId)));
    const dashboardPath = assertContained(runRoot, path.join(runRoot, "artifacts", "dashboard_summary.json"));
    const cardPath = assertContained(runRoot, path.join(runRoot, "artifacts", "model_card.json"));
    const commitPath = assertContained(runRoot, path.join(runRoot, "metadata", "commit.json"));
    const [dashboardBytes, cardBytes, commitBytes] = await Promise.all([readFile(dashboardPath), readFile(cardPath), readFile(commitPath)]);
    if (sha256(dashboardBytes) !== pointer.dashboardSummarySha256 || sha256(cardBytes) !== pointer.modelCardSha256 || sha256(commitBytes) !== pointer.commitRecordSha256) throw new Error("hash");
    const value = JSON.parse(dashboardBytes.toString("utf8")) as Record<string, any>;
    const commit = JSON.parse(commitBytes.toString("utf8")) as Record<string, any>;
    if (commit.status !== "committed" || commit.runId !== pointer.runId || commit.datasetId !== pointer.datasetId || commit.deploymentId !== deploymentId || commit.artifactHashes?.["model_card.json"] !== pointer.modelCardSha256 || commit.artifactHashes?.["dashboard_summary.json"] !== pointer.dashboardSummarySha256) throw new Error("commit identity");
    if (approved && (commit.workflowMode !== "approved_assessment_forecast" || commit.decisionId !== pointer.decisionId || commit.assessmentId !== pointer.assessmentId || commit.authorizationId !== pointer.authorizationId || commit.selectedModelId !== pointer.selectedModelId || commit.decisionScope !== "one_run" || commit.deploymentModelAdopted !== false)) throw new Error("approved commit identity");
    if (value.run?.runId !== pointer.runId || value.run?.datasetId !== pointer.datasetId || value.run?.sourceType !== "uploaded") throw new Error("dashboard identity");
    const calibrated = value.forecast.uncertaintyStatus === "available";
    const dashboard: OverviewViewModel = {
      sourceType: "uploaded",
      latestObservedCases: value.forecast.latestObservedCases,
      forecastCases: value.forecast.forecastReported,
      forecastRaw: value.forecast.forecastRaw,
      forecastChangeCases: value.forecast.forecastReported - value.forecast.latestObservedCases,
      targetPeriod: value.forecast.targetPeriod,
      forecastDirection: value.forecast.direction,
      history: value.history,
      empiricalRange: {
        availabilityStatus: value.forecast.uncertaintyStatus,
        lower: calibrated ? value.forecast.empiricalLower : null,
        upper: calibrated ? value.forecast.empiricalUpper : null,
        nominalCoverage: calibrated ? value.forecast.nominalCoverage : null,
        historicalCoverage: calibrated ? value.forecast.historicalCoverage : null,
        isPredictionInterval: false,
        reason: calibrated
          ? "Dataset-specific empirical range from prior-only rolling-origin residual evidence; historical coverage does not guarantee future coverage."
          : "Dataset-specific temporal calibration has not yet been completed.",
      },
      activeModel: { id: value.model.modelId, label: value.model.modelLabel, adoptionStatus: approved ? "Used for this one-run internal decision; deployment model unchanged" : "Approved under Quick Forecast compatibility policy" },
      modelUse: approved ? { workflowMode: "approved_assessment_forecast", technicalWinnerId: value.model.technicalWinnerModelId, decisionId: value.decision.decisionId, assessmentId: value.decision.assessmentId, decisionOutcome: value.decision.outcome, scope: "one_run", deploymentModelUnchanged: true } : { workflowMode: "quick_forecast", technicalWinnerId: null, decisionId: null, assessmentId: null, decisionOutcome: null, scope: "deployment", deploymentModelUnchanged: false },
      deployment: { mode: "Synthetic capability demonstration", gate: "Benchmark only" },
      preparedness: { availabilityStatus: value.preparedness.availabilityStatus, totalFacilities: 0, bedDeficitFacilities: 0, ns1StockHorizonFacilities: 0, ivFluidStockHorizonFacilities: 0, criticalReviewFacilities: 0 },
      facilitiesRequiringAttention: [], alerts: [],
      latestRun: { runId: value.run.runId, timestamp: value.run.committedAt, status: "Completed", validationStatus: "Validated", acceptedPeriod: value.evidence.validation.acceptedPeriod, completedSteps: value.run.completedSteps, refreshState: "committed" },
    };
    return { sourceType: "uploaded", runId: pointer.runId, dashboard };
  } catch {
    throw new RuntimePublicError("latest_pointer_integrity_failure", "storage", "The latest committed runtime dashboard failed integrity validation.", 503, true);
  }
}
