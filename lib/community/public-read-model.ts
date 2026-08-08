import "server-only";

import type {
  AvailabilityScenario,
  CommunityCurrentV1,
  PublicDashboardResponse,
  PublicForecast,
  PublicForecastResponse,
  PublicHospital,
  PublicPreparedness,
  PublicReadinessStatus,
  PublicSeriesPoint,
} from "./contracts";
import { loadRuntimeConfig } from "@/lib/runtime/config";
import { readVerifiedCurrentForecast, type VerifiedCurrentForecast } from "@/lib/runtime/dashboard-reader";
import { loadDeploymentProductScope } from "@/lib/runtime/deployment-scope";
import { RuntimePublicError } from "@/lib/runtime/errors";
import { readVerifiedCurrentHospitalInventory } from "@/lib/runtime/hospital-inventory-reader";
import { readVerifiedPreparedness } from "@/lib/runtime/preparedness-reader";
import {readCurrentOperationalPreparedness} from "@/lib/runtime/operational-preparedness-reader";
import type { OverviewViewModel } from "@/lib/dashboard-view-model";

type JsonObject = Record<string, unknown>;
const DEPLOYMENT_ID = "dhaka_south";
export const AVAILABLE_SCENARIOS = [
  { id: "baseline_availability", label: "Baseline availability" },
  { id: "constrained_availability", label: "Constrained availability" },
  { id: "severe_constraint", label: "Severe constraint" },
] as const;
export const SCENARIO_EXPLANATION =
  "Availability scenarios test hospital preparedness under the same current forecast. They do not change the epidemiological forecast.";

function object(value: unknown): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new RuntimePublicError("public_read_model_unavailable", "storage", "Verified public information is unavailable.", 503, true);
  }
  return value as JsonObject;
}

function safeInteger(value: unknown): number {
  if (!Number.isSafeInteger(value) || Number(value) < 0) throw new Error("integer");
  return Number(value);
}

function publicForecast(verified: VerifiedCurrentForecast): PublicForecast {
  const source = object(verified.dashboard.forecast);
  const history = verified.dashboard.history;
  if (!Array.isArray(history)
    || Number(source.horizonWeeks) !== 2) {
    throw new RuntimePublicError("unsupported_public_forecast", "storage", "The verified forecast is not publicly presentable.", 503, true);
  }
  const recentObservedSeries: PublicSeriesPoint[] = history.map((candidate) => {
    const point = object(candidate);
    return { period: String(point.period), date: null, cases: safeInteger(point.cases) };
  });
  if (recentObservedSeries.length === 0) throw new Error("history");
  const latestObservedPoint = recentObservedSeries.at(-1)!;
  const forecastPoint: PublicSeriesPoint = {
    period: String(source.targetPeriod),
    date: null,
    cases: safeInteger(source.forecastReported),
  };
  const category = String(verified.forecast.forecastGrowthCategory).toLowerCase();
  if (!["increasing", "decreasing", "stable"].includes(category)) throw new Error("direction");
  const mapping = {
    increasing: { directionLabel: "Expected rise", directionIndicator: "up" },
    decreasing: { directionLabel: "Expected decrease", directionIndicator: "down" },
    stable: { directionLabel: "Expected to remain stable", directionIndicator: "stable" },
  } as const;
  const lower=typeof source.empiricalLower==="number"&&Number.isFinite(source.empiricalLower)?source.empiricalLower:null;
  const upper=typeof source.empiricalUpper==="number"&&Number.isFinite(source.empiricalUpper)?source.empiricalUpper:null;
  const governedInterval=["2.0","2.1"].includes(String(verified.dashboard.schemaVersion))
    && source.forecastPresentationMode==="point_and_interval"
    && source.calibrationStatus==="governed_available"
    && source.uncertaintyStatus==="governed_available"
    && lower!==null&&upper!==null&&lower<=upper;
  return {
    forecastedCases: forecastPoint.cases,
    forecastPeriod: {
      targetPeriod: forecastPoint.period,
      horizonWeeks: 2,
      interpretation: "two_week_ahead_target_period",
    },
    recentObservedSeries,
    forecastSeries: [latestObservedPoint, forecastPoint],
    latestObservedPoint,
    forecastPoint,
    forecast_growth_category: category as keyof typeof mapping,
    ...mapping[category as keyof typeof mapping],
    growthPercentage: null,
    growthComparisonStatus: "equivalent_period_unavailable",
    uncertainty: {
      presentationMode: governedInterval?"point_and_interval":"point_only",
      intervalAvailable: governedInterval,
      lower: governedInterval?lower:null,
      upper: governedInterval?upper:null,
      publicLabel: governedInterval?"Calibrated prediction interval":"Prediction interval unavailable",
      reason: governedInterval
        ?"A model-specific governed interval is available for this exact committed forecast."
        :"Prediction interval unavailable — model-specific calibration has not yet been completed.",
    },
  };
}

export function mapReadinessStatus(status: string): PublicReadinessStatus {
  if (status === "no_calculated_synthetic_gap") return "no_calculated_gap";
  if (status === "insufficient_capacity_reference") return "insufficient_data";
  if (status === "calculated_synthetic_gap_present") return "warning";
  return "not_calculated";
}

function decimalOrNull(value: unknown): number | null {
  if (value === null) return null;
  if (typeof value !== "number" && typeof value !== "string") throw new Error("decimal");
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) throw new Error("decimal");
  return number;
}

function locationLabel(value: unknown): string | null {
  const location = object(value);
  const parts = [location.displayArea, location.cityCorporation, location.administrativeArea]
    .filter((item): item is string => typeof item === "string" && item.trim().length > 0);
  return [...new Set(parts)].join(", ") || null;
}

function mapPreparedness(
  evidence: JsonObject,
  inventory: JsonObject,
): PublicPreparedness {
  if (!Array.isArray(evidence.hospitals) || !Array.isArray(inventory.hospitals)) throw new Error("hospitals");
  const results = new Map(evidence.hospitals.map((candidate) => {
    const row = object(candidate);
    return [String(row.hospitalId), row] as const;
  }));
  const generatedAt = String(evidence.generatedAt);
  const hospitals: PublicHospital[] = inventory.hospitals
    .map(object)
    .filter((hospital) => hospital.active === true && hospital.participationStatus === "included")
    .map((hospital) => {
      const result = results.get(String(hospital.hospitalId));
      if (!result) throw new Error("missing hospital result");
      const status = mapReadinessStatus(String(result.status));
      const capacity = hospital.selectedBedCapacity === null ? null : safeInteger(hospital.selectedBedCapacity);
      return {
        id: String(hospital.hospitalId),
        name: String(hospital.officialName),
        location: locationLabel(hospital.location),
        active: true,
        participationStatus: "included",
        managementDecisionStatus: "pending_review",
        capacityReference: capacity,
        capacityReferenceStatus: capacity === null ? "unavailable" : "available",
        currentAvailableBeds: null,
        currentAvailabilityStatus: "unknown",
        syntheticAvailableBedUnits: decimalOrNull(result.availableResource),
        readinessStatus: status,
        calculatedGap: decimalOrNull(result.syntheticGap),
        ns1RdtStatus: "unknown",
        ivFluidStatus: "unknown",
        lastUpdatedAt: generatedAt,
        evidenceClassification: "synthetic_qualification",
        operationalUseAllowed: false,
      };
    });
  if (hospitals.length !== results.size) throw new Error("unexpected hospital result");
  const capacityKnown = hospitals.filter((hospital) => hospital.capacityReferenceStatus === "available").length;
  const calculatedGap = hospitals.filter((hospital) => hospital.readinessStatus === "warning").length;
  const noGap = hospitals.filter((hospital) => hospital.readinessStatus === "no_calculated_gap").length;
  const insufficient = hospitals.filter((hospital) => hospital.readinessStatus === "insufficient_data").length;
  return {
    selectedScenario: String(evidence.scenarioId) as AvailabilityScenario,
    availableScenarios: [...AVAILABLE_SCENARIOS],
    scenarioExplanation: SCENARIO_EXPLANATION,
    participatingHospitals: hospitals.length,
    capacityKnownHospitals: capacityKnown,
    capacityUnknownHospitals: hospitals.length - capacityKnown,
    calculatedGapHospitals: calculatedGap,
    noCalculatedGapHospitals: noGap,
    insufficientDataHospitals: insufficient,
    hospitals,
    evidenceClassification:"synthetic_qualification",
  };
}

function mapOperationalPreparedness(value:Awaited<ReturnType<typeof readCurrentOperationalPreparedness>>,inventory:JsonObject):PublicPreparedness{
  const inventoryRows=new Map((inventory.hospitals as unknown[]).map(candidate=>{const row=object(candidate);return[String(row.hospitalId),row] as const}));
  const generatedAt=String(value.summary.generatedAt);const hospitals:PublicHospital[]=value.facilities.rows.map(candidate=>{const row=object(candidate);const source=inventoryRows.get(String(row.hospitalId));if(!source)throw new Error("inventory row");const capacity=object(row.capacityReference);const live=object(row.currentLiveAvailability);const metric=object(row.preparednessMetric);const state=object(row.planningState);if(live.value!==null||live.status!=="not_reported")throw new Error("live availability");return{id:String(row.hospitalId),name:String(row.hospitalName),location:locationLabel(source.location),active:true,participationStatus:"included",managementDecisionStatus:"pending_review",capacityReference:capacity.value===null?null:safeInteger(capacity.value),capacityReferenceStatus:capacity.status==="available"?"available":"unavailable",currentAvailableBeds:null,currentAvailabilityStatus:"unknown",syntheticAvailableBedUnits:null,readinessStatus:state.status==="calculated"?(Number(metric.value)>0?"warning":"no_calculated_gap"):"insufficient_data",calculatedGap:decimalOrNull(metric.value),ns1RdtStatus:"unknown",ivFluidStatus:"unknown",lastUpdatedAt:generatedAt,evidenceClassification:"current_operational_preparedness",operationalUseAllowed:true}});
  const known=hospitals.filter(row=>row.capacityReferenceStatus==="available").length;return{selectedScenario:null,availableScenarios:[],scenarioExplanation:"Current preparedness is calculated from the exact-current forecast, active product formula, and current governed inventory.",participatingHospitals:hospitals.length,capacityKnownHospitals:known,capacityUnknownHospitals:hospitals.length-known,calculatedGapHospitals:hospitals.filter(row=>row.readinessStatus==="warning").length,noCalculatedGapHospitals:hospitals.filter(row=>row.readinessStatus==="no_calculated_gap").length,insufficientDataHospitals:hospitals.filter(row=>row.readinessStatus==="insufficient_data").length,hospitals,evidenceClassification:"current_operational_preparedness"};
}

export function parseScenario(value: string | null): AvailabilityScenario | null {
  if (value === null) return null;
  if (!AVAILABLE_SCENARIOS.some((candidate) => candidate.id === value)) {
    throw new RuntimePublicError("unsupported_scenario", "validation", "The availability scenario is unsupported.", 400);
  }
  return value as AvailabilityScenario;
}

export function deriveCommunityTrend(
  latestObservedCases: number | null | undefined,
  pointCases: number | null | undefined,
): CommunityCurrentV1["forecast"]["trend"] {
  if (
    typeof latestObservedCases !== "number"
    || !Number.isFinite(latestObservedCases)
    || typeof pointCases !== "number"
    || !Number.isFinite(pointCases)
  ) {
    return { direction: "unknown", changeCases: null };
  }
  const changeCases = pointCases - latestObservedCases;
  return {
    direction: changeCases > 0 ? "up" : changeCases < 0 ? "down" : "stable",
    changeCases,
  };
}

export async function readPublicForecast(): Promise<PublicForecastResponse> {
  const config = loadRuntimeConfig(false);
  const [scope, verified] = await Promise.all([
    loadDeploymentProductScope(config.repositoryRoot, DEPLOYMENT_ID),
    readVerifiedCurrentForecast(config.runtimeRoot, DEPLOYMENT_ID),
  ]);
  return {
    schemaVersion: "1.0",
    area: { id: scope.internalDeploymentId, displayName: scope.deploymentDisplayName },
    forecast: publicForecast(verified),
    freshness: { updatedAt: String(verified.pointer.committedAt), state: "current" },
    evidence: {
      classification: "synthetic_qualification",
      operationalDhakaValidation: false,
      operationalUseAllowed: false,
    },
  };
}

export async function readPublicDashboard(
  scenario: AvailabilityScenario | null,
): Promise<PublicDashboardResponse> {
  const config = loadRuntimeConfig(false);
  const [scope, forecastAuthority, inventory] = await Promise.all([
    loadDeploymentProductScope(config.repositoryRoot, DEPLOYMENT_ID),
    readVerifiedCurrentForecast(config.runtimeRoot, DEPLOYMENT_ID),
    readVerifiedCurrentHospitalInventory(config.runtimeRoot, DEPLOYMENT_ID),
  ]);
  const operational=await readCurrentOperationalPreparedness();
  const qualification=scenario?await readVerifiedPreparedness(config.runtimeRoot,scenario,forecastAuthority,inventory):null;
  return {
    schemaVersion: "1.0",
    area: { id: scope.internalDeploymentId, displayName: scope.deploymentDisplayName },
    forecast: publicForecast(forecastAuthority),
    preparedness: mapOperationalPreparedness(operational,inventory.inventory),
    qualificationPreparedness:qualification?mapPreparedness(qualification.evidence,inventory.inventory):null,
    freshness: { updatedAt: String(operational.summary.generatedAt), state: "current" },
    evidence: {
      classification: "current_operational_preparedness",
      operationalDhakaValidation: true,
      operationalPreparednessEvidencePublished: true,
      productionFormulaActivated: true,
      operationalUseAllowed: true,
    },
  };
}

export async function readCommunityCurrentV1(): Promise<CommunityCurrentV1> {
  const config = loadRuntimeConfig(false);
  const scope = await loadDeploymentProductScope(config.repositoryRoot, DEPLOYMENT_ID);
  let dashboard: OverviewViewModel;
  try {
    dashboard = (await import("@/lib/runtime/dashboard-reader").then(module => module.readLatestDashboard(DEPLOYMENT_ID))).dashboard;
  } catch (error) {
    if (!(error instanceof RuntimePublicError) || error.code !== "current_forecast_unavailable") throw error;
    return {
      schemaVersion: "1.0", deployment: { id: scope.internalDeploymentId, displayName: scope.deploymentDisplayName }, generatedAt: new Date().toISOString(),
      forecast: { status: "unavailable", targetPeriod: null, pointCases: null, trend: { direction: "unknown", changeCases: null }, series: { observed: [], forecast: [] }, uncertainty: { status: "point_only", nominalLevel: null }, confidence: { status: "unavailable", score: null, band: null } },
      preparedness: { status: "unavailable", facilities: [] },
    };
  }
  const interval = dashboard.empiricalRange.availabilityStatus === "governed_available"
    && dashboard.empiricalRange.isPredictionInterval
    && dashboard.empiricalRange.lower !== null
    && dashboard.empiricalRange.upper !== null;
  const preparednessStatus = dashboard.downstreamEvidence.preparednessStatus === "available"
    ? "available" : dashboard.downstreamEvidence.preparednessStatus === "pending" ? "pending" : "unavailable";
  return {
    schemaVersion: "1.0",
    deployment: { id: scope.internalDeploymentId, displayName: scope.deploymentDisplayName },
    generatedAt: dashboard.latestRun.timestamp,
    forecast: {
      status: "available",
      targetPeriod: dashboard.targetPeriod,
      pointCases: dashboard.forecastCases,
      trend: deriveCommunityTrend(dashboard.latestObservedCases, dashboard.forecastCases),
      series: {
        observed: [...dashboard.history].sort((a, b) => a.period.localeCompare(b.period)).map(point => ({ period: point.period, cases: point.cases })),
        forecast: [{ period: dashboard.targetPeriod, cases: dashboard.forecastCases, lower: interval ? dashboard.empiricalRange.lower : null, upper: interval ? dashboard.empiricalRange.upper : null }],
      },
      uncertainty: { status: interval ? "available" : "point_only", nominalLevel: interval ? dashboard.empiricalRange.nominalCoverage : null },
      confidence: dashboard.monitoring.confidence.status === "available"
        ? { status: "available", score: dashboard.monitoring.confidence.score, band: dashboard.monitoring.confidence.band }
        : { status: dashboard.monitoring.confidence.status, score: null, band: null },
    },
    preparedness: {
      status: preparednessStatus,
      facilities: preparednessStatus === "available" ? dashboard.preparedness.rows.map(row => ({
        facilityName: row.hospitalName,
        participation: "included",
        officialCapacityReference: row.capacityReference.value,
        liveAvailability: null,
        formulaDerivedPreparedness: { value: row.preparednessMetric.value, unit: row.preparednessMetric.unit },
        planningState: row.planningState.status,
      })) : [],
    },
  };
}
