export type WorkflowMode = "quick_forecast" | "assess_dataset";

export type ValidationIssueCategory =
  | "file"
  | "schema"
  | "temporal"
  | "alignment"
  | "eligibility";

export type ValidationIssueSeverity = "error" | "warning";

export interface ValidationIssue {
  code: string;
  category: ValidationIssueCategory;
  severity: ValidationIssueSeverity;
  field?: string;
  message: string;
}

export type AssessmentStatus =
  | "insufficient_history"
  | "candidate_feasibility_only"
  | "full_assessment_eligible"
  | "partial_candidate_set"
  | "assessment_policy_inactive"
  | "assessment_blocked";

export interface AssessmentCandidateEligibility {
  eligible: boolean;
  reasonCodes: string[];
  reasons: string[];
  candidateClass: "naive_baseline" | "learned_model";
  deployabilityClassification:
    | "baseline_not_runtime_deployable"
    | "deployable_learned_model";
  parametersSha256: string;
  minimumTrainingRows: number;
}

export interface RuntimeAssessmentEligibility {
  eligible: boolean;
  assessmentStatus: AssessmentStatus;
  labelledRows: number;
  availableFoldCount: number;
  plannedFoldCount: number;
  foldPlan: {
    trainingWindow: "expanding";
    initialTrainingRows: 104;
    embargoRows: 1;
    validationRowsPerFold: 1;
    stepSizeWeeks: 1;
    horizonWeeks: 2;
    samePlanForAllCandidates: true;
    maximumFoldCapStatus: "governance_pending";
  };
  candidateSetStatus:
    | "complete_candidate_set"
    | "partial_candidate_set"
    | "insufficient_candidate_breadth";
  candidateEligibility: Record<
    | "previous_week_naive"
    | "moving_average_4w"
    | "seasonal_naive_52w"
    | "ridge_regression"
    | "poisson_regression"
    | "random_forest"
    | "gradient_boosting",
    AssessmentCandidateEligibility
  >;
  recommendationEligibility: false;
  recommendationStatus: "evidence_only" | "no_recommendation";
  recommendationStrength: "not_available";
  approvalRequired: true;
  approvalEnabled: false;
  reasonCodes: string[];
  reasons: string[];
  policyId: "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE";
  policyVersion: "p1.4d-1-v1";
  policySha256: string;
}

export interface RuntimeEligibility {
  quickForecast: {
    eligible: boolean;
    reasons: string[];
    reasonCodes: string[];
    approvedModelId: "random_forest";
    uncertaintyStatus:
      | "pending_dataset_specific_calibration"
      | "unavailable_for_uploaded_dataset";
    preparednessStatus:
      | "unavailable_missing_planning_policy"
      | "unavailable_for_uploaded_dataset";
    policyId: "RUNTIME.QUICK_FORECAST.COMPATIBILITY";
    policyVersion: "p1.4f-v1";
    policySha256: string;
  };
  assessDataset: RuntimeAssessmentEligibility;
}

export interface RuntimeValidationResponseSuccess {
  ok: true;
  status: "ready" | "invalid";
  workspaceId: string;
  datasetId: string;
  deploymentId: string;
  validationRecordSha256: string;
  acceptedPeriod?: { start: string; end: string };
  counts: {
    caseRows: number;
    climateRows: number;
    overlapWeeks: number;
    labelledRows: number;
  };
  issues: ValidationIssue[];
  eligibility: RuntimeEligibility;
}

export interface RuntimeErrorResponse {
  ok: false;
  error: {
    code: string;
    category: "upload" | "validation" | "configuration" | "storage" | "internal";
    message: string;
    retryable: boolean;
    correlationId: string;
    issues?: ValidationIssue[];
  };
}

export type RuntimeValidationResponse = RuntimeValidationResponseSuccess | RuntimeErrorResponse;

export interface StartQuickForecastRequest {
  workspaceId: string;
  datasetId: string;
  deploymentId: string;
  validationRecordSha256: string;
}

export interface StartAssessmentRequest {
  workspaceId: string;
  datasetId: string;
  deploymentId: string;
  validationRecordSha256: string;
}

export type RuntimeJobStatus = "queued" | "running" | "committing" | "completed" | "failed" | "timed_out" | "cancelled";
interface RuntimeJobBase {
  schemaVersion: "1.0";
  jobId: string;
  workspaceId: string;
  datasetId: string;
  deploymentId: string;
  validationRecordSha256: string;
  status: RuntimeJobStatus;
  progress: string;
  createdAt: string;
  claimedAt: string | null;
  startedAt: string | null;
  updatedAt: string;
  completedAt: string | null;
  heartbeatAt: string | null;
  workerId: string | null;
  processId: number | null;
  timeoutSeconds: number;
  retryCount: number;
  error: { code: string; message: string; retryable: boolean } | null;
}

export interface QuickForecastJobRecord extends RuntimeJobBase {
  jobKind?: "quick_forecast";
  runId: string;
  workflowMode: "quick_forecast";
  policyId: "RUNTIME.QUICK_FORECAST.COMPATIBILITY";
  policyVersion: "p1.4f-v1";
  policySha256: string;
  committedRunId: string | null;
}

export interface DatasetAssessmentJobRecord extends RuntimeJobBase {
  jobKind: "dataset_assessment";
  assessmentId: string;
  workflowMode: "assess_dataset";
  assessmentPolicyId: "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE";
  assessmentPolicyVersion: "p1.4d-1-v1";
  assessmentPolicySha256: string;
  candidateRegistrySha256: string;
  committedAssessmentId: string | null;
}

export interface ApprovedForecastJobRecord extends RuntimeJobBase {
  jobKind: "approved_forecast";
  runId: string;
  decisionId: string;
  decisionCommitSha256: string;
  authorizationId: string;
  assessmentId: string;
  assessmentCommitSha256: string;
  selectedModelId: "ridge_regression" | "poisson_regression" | "random_forest" | "gradient_boosting";
  selectedModelParameterSha256: string;
  workflowMode: "approved_assessment_forecast";
  committedRunId: string | null;
}

export type RuntimeJobRecord = QuickForecastJobRecord | DatasetAssessmentJobRecord | ApprovedForecastJobRecord;

export type StartQuickForecastResponse =
  | { ok: true; jobId: string; runId: string; status: "queued"; statusUrl: string }
  | RuntimeErrorResponse;

export type StartAssessmentResponse =
  | { ok: true; assessmentId: string; jobId: string; status: "queued"; statusUrl: string; assessmentUrl: string }
  | RuntimeErrorResponse;

export type JobStatusResponse =
  | ({ ok: true; jobKind: "quick_forecast"; jobId: string; runId: string; status: RuntimeJobStatus; progress: string; createdAt: string; startedAt: string | null; updatedAt: string; completedAt: string | null; retryable: boolean; error: RuntimeJobRecord["error"]; committedRunId: string | null })
  | ({ ok: true; jobKind: "dataset_assessment"; jobId: string; assessmentId: string; status: RuntimeJobStatus; progress: string; createdAt: string; startedAt: string | null; updatedAt: string; completedAt: string | null; retryable: boolean; error: RuntimeJobRecord["error"]; committedAssessmentId: string | null })
  | ({ ok: true; jobKind: "approved_forecast"; jobId: string; runId: string; decisionId: string; assessmentId: string; authorizationId: string; status: RuntimeJobStatus; progress: string; createdAt: string; startedAt: string | null; updatedAt: string; completedAt: string | null; retryable: boolean; error: RuntimeJobRecord["error"]; committedRunId: string | null })
  | RuntimeErrorResponse;

export type RuntimeCandidateId =
  | "previous_week_naive" | "moving_average_4w" | "seasonal_naive_52w"
  | "ridge_regression" | "poisson_regression" | "random_forest" | "gradient_boosting";

export interface AssessmentCandidateSummary {
  modelId: RuntimeCandidateId;
  modelLabel: string;
  candidateClass: "naive_baseline" | "learned_model";
  deployabilityClass: "baseline_not_runtime_deployable" | "deployable_learned_model";
  parametersSha256: string;
  eligible: boolean;
  completionStatus: "complete" | "incomplete" | "ineligible";
  reasonCodes: string[];
  reasons: string[];
  successfulFolds: number;
  failedFolds: number;
  selectionEligible: boolean;
  selectionComplexityRank: number;
  metrics: null | { mae: number; rmse: number; wape: number | null; medianAbsoluteError: number; maximumAbsoluteError: number; clippingCount: number; warningCount: number; runtimeSeconds: number };
  executionMode: "fitted_per_fold" | "deterministic_baseline_per_fold";
  historicalPredictionsReused: false;
  foldWinsTiesLosses: null | { better: number; tied: number; worse: number };
}

export interface DatasetAssessmentResultSuccess {
  ok: true;
  schemaVersion: "1.0";
  assessmentId: string;
  jobId: string;
  datasetId: string;
  deploymentId: string;
  sourceType: "uploaded";
  acceptedPeriod: { start: string; end: string };
  labelledRows: 173;
  committedAt: string;
  assessmentStatus: "assessment_complete";
  approvalStatus: "approval_pending";
  adoptionStatus: "not_adopted";
  foldPolicy: { policyId: string; policyVersion: string; plannedFoldCount: 68; initialTrainingRows: 104; embargoRows: 1; validationRowsPerFold: 1; stepSizeWeeks: 1; horizonWeeks: 2; samePlanForAllCandidates: true };
  foldPlanSha256: string;
  candidateSetStatus: "complete_candidate_set" | "partial_candidate_set" | "insufficient_candidate_breadth";
  candidates: AssessmentCandidateSummary[];
  technicalWinnerModelId: RuntimeCandidateId | null;
  selectionReason: string;
  tieStage: string | null;
  baselineRequirementSatisfied: boolean;
  learnedModelRequirementSatisfied: boolean;
  recommendationStatus: "evidence_only" | "no_recommendation";
  recommendationStrength: "not_available";
  approvalRequired: true;
  approvalEnabled: false;
  limitations: string[];
  evidenceHashes: { rollingValidationSha256: string; candidateComparisonSha256: string; recommendationSha256: string };
  provenance: { validationRecordSha256: string; assessmentPolicySha256: string; candidateRegistrySha256: string; featureOrderSha256: string };
  integrity: { assessmentSummarySha256: string; assessmentCommitSha256: string };
}

export type DatasetAssessmentResponse = DatasetAssessmentResultSuccess | RuntimeErrorResponse;

export type DecisionChoice = "approve_technical_winner" | "keep_current_model" | "defer" | "reject_assessment";
export interface RecordDecisionRequest { decision: DecisionChoice; reason: string; expectedAssessmentSummarySha256: string }
export interface DecisionResultSuccess { ok:true; decisionId:string; assessmentId:string; decision:DecisionChoice; selectedModelId:RuntimeCandidateId|null; selectedModelLabel:string|null; decisionScope:"one_run"; operatorType:"trusted_internal_unverified"; institutionalApproval:false; reason:string; decisionStatus:string; forecastAuthorized:boolean; authorizationId:string|null; authorizationStatus:"not_authorized"|"authorization_incomplete"|"available"|"reserved"|"consumed"; createdAt:string; limitations:string[]; decisionCommitSha256:string }
export type DecisionResponse = DecisionResultSuccess | RuntimeErrorResponse;
export interface StartApprovedForecastRequest { expectedDecisionCommitSha256: string }
export type StartApprovedForecastResponse = {ok:true;jobId:string;runId:string;decisionId:string;authorizationId:string;status:"queued";statusUrl:string}|RuntimeErrorResponse;

export type LatestDashboardResponse =
  | { ok: true; sourceType: "bundled_benchmark" | "uploaded"; runId: string; dashboard: import("@/lib/dashboard-view-model").OverviewViewModel }
  | RuntimeErrorResponse;

export interface RuntimeFileMetadata {
  originalName: string;
  storedName: "dengue.csv" | "climate.csv";
  sizeBytes: number;
  sha256: string;
}

export interface RuntimeWorkspaceMetadata {
  schemaVersion: "1.0";
  workspaceId: string;
  correlationId: string;
  deploymentId: string;
  workflowMode: WorkflowMode;
  status: "uploaded" | "validating" | "ready" | "invalid";
  createdAt: string;
  updatedAt: string;
  originalFiles: {
    dengue: RuntimeFileMetadata;
    climate: RuntimeFileMetadata;
  };
  datasetId?: string;
}
