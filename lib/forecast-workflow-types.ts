import type { ArtifactProvenance, CandidateComparisonSummary, DashboardSummaryUncertainty, DeploymentGate, Directive, FeatureDiagnostics, ForecastOutput, PipelineRunSummary } from "./types";
import type { DatasetAssessmentResultSuccess, DecisionResultSuccess, JobStatusResponse, RuntimeErrorResponse, RuntimeValidationResponseSuccess, WorkflowMode } from "./runtime/contracts";

export interface OverviewViewModel {
  latestObservedCases: number;
  pointForecast: number;
  empiricalLower: number;
  empiricalUpper: number;
  targetPeriod: string;
  forecastDirection: string;
  activeModelLabel: string;
  deploymentMode: string;
  deploymentGate: DeploymentGate;
  latestRun: Pick<PipelineRunSummary, "run_timestamp" | "status"> & { runId: string; completedSteps: number };
  facilities: Directive[];
  activeAlerts: Array<{ facilityName: string; level: string; message: string }>;
}

export interface PreparednessViewModel {
  scenarios: ForecastOutput["preparedness_scenarios"];
  facilities: Directive[];
  empiricalRange: Pick<DashboardSummaryUncertainty, "interval_lower_reported" | "interval_upper_reported" | "point_forecast_reported">;
  scenarioRelationship: string;
}

export interface EvidenceViewModel {
  comparison: CandidateComparisonSummary;
  uncertainty: DashboardSummaryUncertainty;
  explainability: FeatureDiagnostics;
  provenance: ArtifactProvenance;
  deploymentMode: string;
  deploymentGate: DeploymentGate;
  limitations: string[];
}

export type RecommendationStrength = "strong" | "moderate" | "weak" | "not_available";
export type ModelSuitabilityAssessment = DatasetAssessmentResultSuccess;

export type ModelApprovalDecision = DecisionResultSuccess;
export interface ForecastRunResult {
  runId: string;
  status: "completed" | "failed";
  forecast?: { point: number; lower: null; upper: null; targetPeriod: string };
  uncertaintyStatus?: "pending_dataset_specific_calibration" | "pending_selected_model_calibration";
  preparednessStatus?: "unavailable_missing_planning_policy";
  error?: string;
}

export type { WorkflowMode } from "./runtime/contracts";
export type ProcessingStatus = "idle" | "validating" | "blocked" | "ready" | "queued" | "running" | "committing" | "completed" | "failed" | "timed_out" | "cancelled";
export type WorkflowStep = "upload" | "validate" | "choose" | "review" | "results";
export interface LocalFilePreview { key: "dengue" | "climate"; file: File; detectedColumns: string[]; missingColumns: string[]; approximateRowCount: number; headerPreviewComplete: boolean; }
export type ServerValidationState =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "ready"; response: RuntimeValidationResponseSuccess }
  | { status: "invalid"; response: RuntimeValidationResponseSuccess }
  | { status: "failed"; error: RuntimeErrorResponse["error"] };
export interface ForecastWorkflowState {
  step: WorkflowStep;
  files: Partial<Record<"dengue" | "climate", LocalFilePreview>>;
  mode: WorkflowMode | null;
  validatedWorkflowMode: WorkflowMode | null;
  workflowRevalidationRequired: boolean;
  processingStatus: ProcessingStatus;
  serverValidation: ServerValidationState;
  workspaceId: string | null;
  datasetId: string | null;
  job: JobStatusResponse | null;
  assessment: ModelSuitabilityAssessment | null;
  approval: ModelApprovalDecision | null;
  result: ForecastRunResult | null;
}
