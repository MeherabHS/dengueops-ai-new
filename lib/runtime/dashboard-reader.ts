import { createHash } from "node:crypto";
import { readFile,readdir } from "node:fs/promises";
import path from "node:path";
import type { OverviewViewModel } from "@/lib/dashboard-view-model";
import { governedModelLabel } from "@/lib/status-labels";
import { loadRuntimeConfig } from "./config";
import { RuntimePublicError } from "./errors";
import { assertContained, deploymentRuntimePaths, runtimeCollectionPaths } from "./paths";
import {readCurrentOperationalPreparedness} from "./operational-preparedness-reader";
import {resolveCurrentPreparednessAuthority} from "./preparedness-authority";

const sha256 = (value: Buffer) => createHash("sha256").update(value).digest("hex");
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[a-f0-9]{64}$/;
const EPI_PERIOD = /^\d{4}-W(?:0[1-9]|[1-4]\d|5[0-3])$/;

type JsonObject = Record<string, unknown>;

export interface VerifiedCurrentForecast {
  pointer: JsonObject;
  pointerSha256: string;
  dashboard: JsonObject;
  forecast: JsonObject;
  uncertainty: JsonObject;
  chart: JsonObject;
  commit: JsonObject;
  commitSha256: string;
  forecastSha256: string;
}

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("object");
  return value as JsonObject;
}

function exactKeys(value: JsonObject, keys: string[]): boolean {
  return Object.keys(value).sort().join("|") === [...keys].sort().join("|");
}

function integer(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function acceptedPeriodLabel(value: unknown): string {
  const period = object(value);
  if (
    !exactKeys(period, ["start", "end"])
    || typeof period.start !== "string"
    || typeof period.end !== "string"
    || !EPI_PERIOD.test(period.start)
    || !EPI_PERIOD.test(period.end)
  ) {
    throw new Error("accepted period");
  }
  return `${period.start} – ${period.end}`;
}

export function dashboardModelLabel(value: unknown): string {
  if (typeof value !== "string") throw new Error("model identity");
  const label = governedModelLabel(value);
  if (!label) throw new Error("model identity");
  return label;
}

export async function readVerifiedCurrentForecast(
  runtimeRoot: string,
  deploymentId: string,
): Promise<VerifiedCurrentForecast> {
  const deployment = deploymentRuntimePaths(runtimeRoot, deploymentId);
  let pointerBytes: Buffer;
  try {
    pointerBytes = await readFile(deployment.latest);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      throw new RuntimePublicError("current_forecast_unavailable", "storage", "The current verified forecast is unavailable.", 503, true);
    }
    throw error;
  }
  try {
    const pointer = object(JSON.parse(pointerBytes.toString("utf8")));
    const approved = pointer.workflowMode === "approved_assessment_forecast";
    const pointerKeys = approved
      ? ["schemaVersion", "deploymentId", "runId", "datasetId", "workflowMode", "sourceType", "decisionId", "assessmentId", "authorizationId", "selectedModelId", "committedAt", "modelCardSha256", "dashboardSummarySha256", "commitRecordSha256"]
      : ["schemaVersion", "deploymentId", "runId", "datasetId", "workflowMode", "sourceType", "committedAt", "modelCardSha256", "dashboardSummarySha256", "commitRecordSha256"];
    if (!exactKeys(pointer, pointerKeys)
      || pointer.schemaVersion !== "1.0"
      || pointer.deploymentId !== deploymentId
      || !["quick_forecast", "approved_assessment_forecast"].includes(String(pointer.workflowMode))
      || pointer.sourceType !== "uploaded"
      || !UUID.test(String(pointer.runId))
      || (approved && (!UUID.test(String(pointer.decisionId)) || !UUID.test(String(pointer.assessmentId)) || !UUID.test(String(pointer.authorizationId))))
      || !SHA.test(String(pointer.datasetId))
      || !SHA.test(String(pointer.modelCardSha256))
      || !SHA.test(String(pointer.dashboardSummarySha256))
      || !SHA.test(String(pointer.commitRecordSha256))) {
      throw new Error("pointer identity");
    }
    const runs = runtimeCollectionPaths(runtimeRoot).runs;
    const runRoot = assertContained(runs, path.join(runs, String(pointer.runId)));
    const artifactRoot = assertContained(runRoot, path.join(runRoot, "artifacts"));
    const paths = {
      dashboard: assertContained(artifactRoot, path.join(artifactRoot, "dashboard_summary.json")),
      card: assertContained(artifactRoot, path.join(artifactRoot, "model_card.json")),
      forecast: assertContained(artifactRoot, path.join(artifactRoot, "forecast_output.json")),
      uncertainty: assertContained(artifactRoot, path.join(artifactRoot, "forecast_uncertainty.json")),
      chart: assertContained(artifactRoot, path.join(artifactRoot, "chart_data.json")),
      commit: assertContained(runRoot, path.join(runRoot, "metadata", "commit.json")),
    };
    const [dashboardBytes, cardBytes, forecastBytes, uncertaintyBytes, chartBytes, commitBytes] = await Promise.all([
      readFile(paths.dashboard),
      readFile(paths.card),
      readFile(paths.forecast),
      readFile(paths.uncertainty),
      readFile(paths.chart),
      readFile(paths.commit),
    ]);
    if (sha256(dashboardBytes) !== pointer.dashboardSummarySha256
      || sha256(cardBytes) !== pointer.modelCardSha256
      || sha256(commitBytes) !== pointer.commitRecordSha256) {
      throw new Error("pointer hash");
    }
    const dashboard = object(JSON.parse(dashboardBytes.toString("utf8")));
    const forecast = object(JSON.parse(forecastBytes.toString("utf8")));
    const uncertainty = object(JSON.parse(uncertaintyBytes.toString("utf8")));
    const chart = object(JSON.parse(chartBytes.toString("utf8")));
    const commit = object(JSON.parse(commitBytes.toString("utf8")));
    const artifactHashes = object(commit.artifactHashes);
    if (commit.status !== "committed"
      || commit.runId !== pointer.runId
      || commit.datasetId !== pointer.datasetId
      || commit.deploymentId !== deploymentId
      || commit.workflowMode !== pointer.workflowMode
      || artifactHashes["model_card.json"] !== pointer.modelCardSha256
      || artifactHashes["dashboard_summary.json"] !== pointer.dashboardSummarySha256
      || artifactHashes["forecast_output.json"] !== sha256(forecastBytes)
      || artifactHashes["forecast_uncertainty.json"] !== sha256(uncertaintyBytes)
      || artifactHashes["chart_data.json"] !== sha256(chartBytes)) {
      throw new Error("commit identity");
    }
    if (approved && (commit.decisionId !== pointer.decisionId
      || commit.assessmentId !== pointer.assessmentId
      || commit.authorizationId !== pointer.authorizationId
      || commit.selectedModelId !== pointer.selectedModelId
      || commit.decisionScope !== "one_run"
      || commit.deploymentModelAdopted !== false)) {
      throw new Error("approved commit identity");
    }
    const run = object(dashboard.run);
    const dashboardForecast = object(dashboard.forecast);
    const chartForecast = object(chart.forecast);
    if (run.runId !== pointer.runId
      || run.datasetId !== pointer.datasetId
      || run.sourceType !== "uploaded"
      || forecast.runId !== pointer.runId
      || forecast.datasetId !== pointer.datasetId
      || forecast.deploymentId !== deploymentId
      || forecast.workflowMode !== pointer.workflowMode
      || uncertainty.runId !== pointer.runId
      || chart.runId !== pointer.runId
      || !Array.isArray(chart.history)
      || !Array.isArray(dashboard.history)
      || JSON.stringify(chart.history) !== JSON.stringify(dashboard.history)
      || chartForecast.period !== forecast.targetPeriod
      || chartForecast.cases !== forecast.forecastReported
      || dashboardForecast.forecastReported !== forecast.forecastReported
      || dashboardForecast.latestObservedCases !== forecast.latestObservedCases
      || dashboardForecast.targetPeriod !== forecast.targetPeriod
      || dashboardForecast.direction !== forecast.forecastGrowthCategory
      || object(chart.history.at(-1)).cases !== forecast.latestObservedCases
      || !integer(forecast.forecastReported)
      || !integer(forecast.latestObservedCases)) {
      throw new Error("artifact identity");
    }
    return {
      pointer,
      pointerSha256: sha256(pointerBytes),
      dashboard,
      forecast,
      uncertainty,
      chart,
      commit,
      commitSha256: sha256(commitBytes),
      forecastSha256: sha256(forecastBytes),
    };
  } catch (error) {
    if (error instanceof RuntimePublicError) throw error;
    throw new RuntimePublicError("latest_pointer_integrity_failure", "storage", "The latest committed runtime forecast failed integrity validation.", 503, true);
  }
}

function overviewFromVerified(verified: VerifiedCurrentForecast,operational:Awaited<ReturnType<typeof readCurrentOperationalPreparedness>>|null,preparednessReason:string|null,calculating=false): OverviewViewModel {
  const dashboard = verified.dashboard;
  const forecast = object(dashboard.forecast);
  const model = object(dashboard.model);
  const run = object(dashboard.run);
  const evidence = object(dashboard.evidence);
  const validation = object(evidence.validation);
  const preparedness = object(dashboard.preparedness);
  const approved = verified.pointer.workflowMode === "approved_assessment_forecast";
  const decision = approved ? object(dashboard.decision) : {};
  const legacyInterval=dashboard.schemaVersion==="1.0"
    && forecast.uncertaintyStatus==="available";
  const governedInterval=["2.0","2.1"].includes(String(dashboard.schemaVersion))
    && forecast.uncertaintyStatus==="governed_available"
    && forecast.calibrationStatus==="governed_available"
    && forecast.forecastPresentationMode==="point_and_interval";
  const lower=typeof forecast.empiricalLower==="number"&&Number.isFinite(forecast.empiricalLower)?forecast.empiricalLower:null;
  const upper=typeof forecast.empiricalUpper==="number"&&Number.isFinite(forecast.empiricalUpper)?forecast.empiricalUpper:null;
  const calibrated=(legacyInterval||governedInterval)&&lower!==null&&upper!==null&&lower<=upper;
  const value = {
    forecast: {
      uncertaintyStatus: calibrated?(governedInterval?"governed_available":"available"):"unavailable" as OverviewViewModel["empiricalRange"]["availabilityStatus"],
      empiricalLower: lower,
      empiricalUpper: upper,
      nominalCoverage: Number(forecast.nominalCoverage),
      historicalCoverage: Number(forecast.historicalCoverage),
    },
    preparedness: {
      availabilityStatus: String(preparedness.availabilityStatus) as OverviewViewModel["preparedness"]["availabilityStatus"],
    },
  };
  return {
    sourceType: "uploaded",
    latestObservedCases: Number(forecast.latestObservedCases),
    forecastCases: Number(forecast.forecastReported),
    forecastRaw: Number(forecast.forecastRaw),
    forecastChangeCases: Number(forecast.forecastReported) - Number(forecast.latestObservedCases),
    targetPeriod: String(forecast.targetPeriod),
    forecastDirection: String(forecast.direction),
    history: dashboard.history as OverviewViewModel["history"],
    empiricalRange: {
      availabilityStatus: value.forecast.uncertaintyStatus,
      lower: calibrated ? value.forecast.empiricalLower : null,
      upper: calibrated ? value.forecast.empiricalUpper : null,
      nominalCoverage: calibrated ? value.forecast.nominalCoverage : null,
      historicalCoverage: calibrated ? value.forecast.historicalCoverage : null,
      isPredictionInterval: false,
      reason: calibrated
        ? "Dataset-specific empirical range from prior-only rolling-origin residual evidence; historical coverage does not guarantee future coverage."
        : "Prediction interval unavailable — model-specific calibration has not yet been completed.",
    },
    activeModel: {
      id: String(model.modelId),
      label: dashboardModelLabel(model.modelId),
      adoptionStatus: approved ? "Used for this one-run internal decision; deployment model unchanged" : "Approved under Quick Forecast compatibility policy",
    },
    modelUse: approved
      ? { workflowMode: "approved_assessment_forecast", technicalWinnerId: String(model.technicalWinnerModelId), decisionId: String(decision.decisionId), assessmentId: String(decision.assessmentId), decisionOutcome: String(decision.outcome), scope: "one_run", deploymentModelUnchanged: true }
      : { workflowMode: "quick_forecast", technicalWinnerId: null, decisionId: null, assessmentId: null, decisionOutcome: null, scope: "deployment", deploymentModelUnchanged: false },
    deployment: { mode: "Synthetic capability demonstration", gate: "Benchmark only" },
    preparedness: operational?{
      availabilityStatus:"available",reason:null,formulaLabel:String(object(operational.summary.formula).label),rows:operational.facilities.rows as unknown as OverviewViewModel["preparedness"]["rows"],
      totalFacilities:operational.facilities.rows.length,bedDeficitFacilities:operational.facilities.rows.filter(row=>Number(object(row.preparednessMetric).value)>0).length,ns1StockHorizonFacilities:0,ivFluidStockHorizonFacilities:0,criticalReviewFacilities:0,
    }:{availabilityStatus:calculating?"calculating":value.preparedness.availabilityStatus,reason:calculating?"Operational preparedness is calculating for the current forecast, formula, policy, and inventory.":preparednessReason,formulaLabel:null,rows:[],totalFacilities:0,bedDeficitFacilities:0,ns1StockHorizonFacilities:0,ivFluidStockHorizonFacilities:0,criticalReviewFacilities:0},
    facilitiesRequiringAttention: [],
    alerts: [],
    latestRun: {
      runId: String(run.runId),
      timestamp: String(run.committedAt),
      status: "Completed",
      validationStatus: "Validated",
      acceptedPeriod: acceptedPeriodLabel(validation.acceptedPeriod),
      completedSteps: Number(run.completedSteps),
      refreshState: "committed",
    },
  };
}

export async function readLatestDashboard(
  deploymentId: string,
): Promise<{ sourceType: "uploaded"; runId: string; dashboard: OverviewViewModel }> {
  const config = loadRuntimeConfig(false);
  const verified = await readVerifiedCurrentForecast(config.runtimeRoot, deploymentId);
  let operational:Awaited<ReturnType<typeof readCurrentOperationalPreparedness>>|null=null;let reason:string|null=null;let calculating=false;
  try{operational=await readCurrentOperationalPreparedness()}catch(error){if(error instanceof RuntimePublicError){reason=error.message;try{const authority=await resolveCurrentPreparednessAuthority();const collections=runtimeCollectionPaths(config.runtimeRoot);for(const directory of [collections.pendingJobs,collections.runningJobs])for(const name of await readdir(directory)){if(!name.endsWith(".json"))continue;const job=object(JSON.parse(await readFile(path.join(directory,name),"utf8")));if(job.jobKind==="operational_preparedness"&&job.authoritySnapshotSha256===authority.authoritySnapshotSha256)calculating=true}}catch{}}else throw error}
  return { sourceType: "uploaded", runId: String(verified.pointer.runId), dashboard: overviewFromVerified(verified,operational,reason,calculating) };
}
