import {
  chartData,
  dashboardSummary,
  directives,
  forecastOutput,
  pipelineRunSummary,
} from "@/lib/demo-data";
import { modelLabel, statusLabel } from "@/lib/status-labels";

export type DashboardRefreshState =
  | "committed"
  | "loading_latest_commit"
  | "new_commit_available"
  | "refreshing"
  | "refresh_failed"
  | "stale_commit";

export interface HistoricalCasePoint {
  period: string;
  cases: number;
}

export interface FacilityAttentionViewModel {
  id: string;
  name: string;
  configuredBeds: number;
  projectedDemand: number;
  reserveOrDeficit: number;
  status: "Critical" | "Deficit" | "Watch";
  statusReason: string;
}

export interface AlertViewModel {
  id: string;
  facilityName: string;
  severity: string;
  message: string;
}

export interface LatestRunViewModel {
  runId: string;
  timestamp: string;
  status: string;
  validationStatus: string;
  acceptedPeriod: string;
  completedSteps: number;
  refreshState: DashboardRefreshState;
}

export interface OverviewViewModel {
  sourceType: "bundled_benchmark" | "uploaded";
  latestObservedCases: number;
  forecastCases: number;
  forecastRaw: number;
  forecastChangeCases: number;
  targetPeriod: string;
  forecastDirection: string;
  history: HistoricalCasePoint[];
  empiricalRange: {
    availabilityStatus: "available" | "pending_dataset_specific_calibration" | "pending_selected_model_calibration" | "unavailable_for_uploaded_dataset";
    lower: number | null;
    upper: number | null;
    nominalCoverage: number | null;
    historicalCoverage: number | null;
    isPredictionInterval: false;
    reason: string | null;
  };
  activeModel: {
    id: string;
    label: string;
    adoptionStatus: string;
  };
  modelUse: { workflowMode: "bundled_benchmark" | "quick_forecast" | "approved_assessment_forecast"; technicalWinnerId: string | null; decisionId: string | null; assessmentId: string | null; decisionOutcome: string | null; scope: "deployment" | "one_run"; deploymentModelUnchanged: boolean };
  deployment: { mode: string; gate: string };
  preparedness: {
    availabilityStatus: "available" | "unavailable_missing_planning_policy" | "unavailable_for_uploaded_dataset";
    totalFacilities: number;
    bedDeficitFacilities: number;
    ns1StockHorizonFacilities: number;
    ivFluidStockHorizonFacilities: number;
    criticalReviewFacilities: number;
  };
  facilitiesRequiringAttention: FacilityAttentionViewModel[];
  alerts: AlertViewModel[];
  latestRun: LatestRunViewModel;
}

type ChartDataProjection = { case_trend?: Array<{ label: string; cases: number }> };

function periodLabel(period?: { epi_year: number; epi_week: number }): string {
  return period ? `${period.epi_year}-W${String(period.epi_week).padStart(2, "0")}` : "Unavailable";
}

function buildFacilityAttention(): FacilityAttentionViewModel[] {
  return directives
    .map((facility) => {
      const critical = facility.inventory_alerts.some((alert) => alert.alert_level.toLowerCase() === "critical");
      const deficit = facility.bed_gap_expected > 0;
      const stockHorizon = (facility.sdh_ns1_expected ?? Infinity) <= 14 || (facility.sdh_iv_fluid_expected ?? Infinity) <= 14;
      const status = critical ? "Critical" : deficit ? "Deficit" : "Watch";
      const rank = critical ? 3 : deficit ? 2 : stockHorizon ? 1 : 0;
      return {
        rank,
        value: {
          id: facility.facility_id,
          name: facility.facility_name,
          configuredBeds: facility.dengue_bed_capacity_demo,
          projectedDemand: facility.projected_bed_load_expected,
          reserveOrDeficit: facility.dengue_bed_capacity_demo - facility.projected_bed_load_expected,
          status,
          statusReason: critical ? "Critical inventory alert" : deficit ? "Projected bed deficit" : "Stock horizon review",
        } satisfies FacilityAttentionViewModel,
      };
    })
    .filter(({ rank }) => rank > 0)
    .sort((left, right) => right.rank - left.rank || left.value.reserveOrDeficit - right.value.reserveOrDeficit)
    .slice(0, 4)
    .map(({ value }) => value);
}

export function buildBundledOverviewViewModel(): OverviewViewModel {
  const history = ((chartData as ChartDataProjection).case_trend ?? []).map((point) => ({ period: point.label, cases: point.cases }));
  const uncertainty = dashboardSummary.uncertainty;
  const totalFacilities = directives.length;
  const accepted = dashboardSummary.workflow_metadata?.accepted_period;
  const activeModelId = dashboardSummary.candidate_model_comparison.current_forecast_model;
  return {
    sourceType: "bundled_benchmark",
    latestObservedCases: forecastOutput.latest_observed_cases,
    forecastCases: uncertainty.point_forecast_reported,
    forecastRaw: uncertainty.point_forecast_raw,
    forecastChangeCases: uncertainty.point_forecast_reported - forecastOutput.latest_observed_cases,
    targetPeriod: `${forecastOutput.target_epi_year}-W${String(forecastOutput.target_epi_week).padStart(2, "0")}`,
    forecastDirection: forecastOutput.forecast_growth_category,
    history,
    empiricalRange: {
      availabilityStatus: "available",
      lower: uncertainty.interval_lower_reported,
      upper: uncertainty.interval_upper_reported,
      nominalCoverage: uncertainty.nominal_coverage,
      historicalCoverage: uncertainty.observed_historical_coverage,
      isPredictionInterval: uncertainty.is_prediction_interval,
      reason: null,
    },
    activeModel: {
      id: activeModelId,
      label: modelLabel(activeModelId),
      adoptionStatus: statusLabel(dashboardSummary.candidate_model_comparison.adoption_status),
    },
    modelUse: { workflowMode: "bundled_benchmark", technicalWinnerId: activeModelId, decisionId: null, assessmentId: null, decisionOutcome: null, scope: "deployment", deploymentModelUnchanged: false },
    deployment: {
      mode: statusLabel(dashboardSummary.deployment_profile?.demonstration_status),
      gate: statusLabel(dashboardSummary.deployment_profile?.deployment_gate),
    },
    preparedness: {
      availabilityStatus: "available",
      totalFacilities,
      bedDeficitFacilities: directives.filter((facility) => facility.bed_gap_expected > 0).length,
      ns1StockHorizonFacilities: directives.filter((facility) => (facility.sdh_ns1_expected ?? Infinity) <= 14).length,
      ivFluidStockHorizonFacilities: directives.filter((facility) => (facility.sdh_iv_fluid_expected ?? Infinity) <= 14).length,
      criticalReviewFacilities: directives.filter((facility) => facility.inventory_alerts.some((alert) => alert.alert_level.toLowerCase() === "critical")).length,
    },
    facilitiesRequiringAttention: buildFacilityAttention(),
    alerts: directives.flatMap((facility) => facility.inventory_alerts.map((alert, index) => ({
      id: `${facility.facility_id}-${index}`,
      facilityName: facility.facility_name,
      severity: statusLabel(alert.alert_level),
      message: alert.message,
    }))).slice(0, 3),
    latestRun: {
      runId: pipelineRunSummary.provenance.run_id,
      timestamp: pipelineRunSummary.run_timestamp,
      status: statusLabel(pipelineRunSummary.status),
      validationStatus: statusLabel(dashboardSummary.workflow_metadata?.validation_status ?? pipelineRunSummary.provenance.validation_status),
      acceptedPeriod: accepted ? `${periodLabel(accepted.start)} to ${periodLabel(accepted.end)}` : "Committed model period unavailable",
      completedSteps: pipelineRunSummary.completed_steps.length,
      refreshState: "committed",
    },
  };
}

export const bundledOverviewViewModel = buildBundledOverviewViewModel();
