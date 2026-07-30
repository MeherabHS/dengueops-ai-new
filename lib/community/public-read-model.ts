import "server-only";

import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";
import type {
  AvailabilityScenario,
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

const canonical = (value: unknown): string => Array.isArray(value)
  ? `[${value.map(canonical).join(",")}]`
  : value && typeof value === "object"
    ? `{${Object.entries(value as JsonObject).sort(([left], [right]) => left.localeCompare(right)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`
    : JSON.stringify(value);

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
  };
}

async function assertProductionFormulaUnconfigured(repositoryRoot: string): Promise<void> {
  const policyPath = path.join(repositoryRoot, "config", "deployments", DEPLOYMENT_ID, "formula_activation_policy.json");
  const policy = object(JSON.parse(await readFile(policyPath, "utf8")));
  const withoutHash = Object.fromEntries(Object.entries(policy).filter(([key]) => key !== "policySha256"));
  const expectedSha = createHash("sha256").update(canonical(withoutHash)).digest("hex");
  if (policy.policyId !== "RUNTIME.FORMULA.ACTIVATION"
    || policy.deploymentId !== DEPLOYMENT_ID
    || policy.inventoryGapActivationStatus !== "not_configured"
    || Object.keys(object(policy.formulaBindings)).length !== 0
    || policy.policySha256 !== expectedSha) {
    throw new RuntimePublicError("production_formula_scope_mismatch", "configuration", "Public qualification data is unavailable.", 503, true);
  }
}

export function parseScenario(value: string | null): AvailabilityScenario | null {
  if (value === null) return null;
  if (!AVAILABLE_SCENARIOS.some((candidate) => candidate.id === value)) {
    throw new RuntimePublicError("unsupported_scenario", "validation", "The availability scenario is unsupported.", 400);
  }
  return value as AvailabilityScenario;
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
    assertProductionFormulaUnconfigured(config.repositoryRoot),
  ]);
  const packageAuthority = await readVerifiedPreparedness(
    config.runtimeRoot,
    scenario,
    forecastAuthority,
    inventory,
  );
  return {
    schemaVersion: "1.0",
    area: { id: scope.internalDeploymentId, displayName: scope.deploymentDisplayName },
    forecast: publicForecast(forecastAuthority),
    preparedness: mapPreparedness(packageAuthority.evidence, inventory.inventory),
    freshness: { updatedAt: String(packageAuthority.evidence.generatedAt), state: "current" },
    evidence: {
      classification: "synthetic_qualification",
      operationalDhakaValidation: false,
      operationalPreparednessEvidencePublished: false,
      productionFormulaActivated: false,
      operationalUseAllowed: false,
    },
  };
}
