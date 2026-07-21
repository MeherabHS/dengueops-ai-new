export type WorkflowMode = "quick_forecast" | "assess_dataset" | "forecast_outcome_monitoring";

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
  minimumFoldCount: number;
  maximumFoldCount: number;
  foldCapApplied: boolean;
  selectedValidationStartIndex: number | null;
  selectedValidationEndIndex: number | null;
  foldPlan: {
    trainingWindow: "expanding";
    initialTrainingRows: 104;
    embargoRows: 1;
    validationRowsPerFold: 1;
    stepSizeWeeks: 1;
    horizonWeeks: 2;
    samePlanForAllCandidates: true;
    firstAvailableValidationIndex: number;
    minimumFoldCount: number;
    maximumFoldCount: number;
    foldSelectionRule: string | null;
    maximumFoldCapStatus: "governance_pending" | "applied" | "not_applied";
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
  policyVersion: "p1.4d-1-v1" | "p2-v1";
  policySha256: string;
  assessmentPolicyId: "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE";
  assessmentPolicyVersion: "p1.4d-1-v1" | "p2-v1";
  assessmentPolicySha256: string;
  assessmentEligibilityStatus: AssessmentStatus;
  decisionCompatibilityStatus: "phase1_decision_policy_available" | "phase2_decision_policy_not_yet_available";
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
  activeModelAuthority?:{authoritySource:"committed_assignment"|"historical_profile_fallback_pending_explicit_bootstrap";authoritySnapshotSha256:string;modelId:"random_forest";bootstrapRequired:boolean;quickForecastCompatible:true};
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

export interface HistoricalQuickForecastJob extends RuntimeJobBase {
    jobKind?: "quick_forecast";
    runId: string;
    workflowMode: "quick_forecast";
  policyId: "RUNTIME.QUICK_FORECAST.COMPATIBILITY";
    policyVersion: "p1.4f-v1";
    policySha256: string;
    committedRunId: string | null;
}

interface AssignmentAwareQuickBase extends HistoricalQuickForecastJob {
  activeModelAuthoritySource:"committed_assignment"|"historical_profile_fallback_pending_explicit_bootstrap";
  authoritySnapshotSha256:string; resolvedModelId:"random_forest"; resolvedModelFamily:"RandomForestRegressor"; resolvedModelParameterSha256:string;
  resolvedFeatureOrderSha256:string; resolvedCandidateRegistrySha256:string; quickPolicyId:"RUNTIME.QUICK_FORECAST.COMPATIBILITY"; quickPolicyVersion:"p1.4f-v1"; quickPolicySha256:string;
}
export interface CommittedAssignmentQuickForecastJob extends AssignmentAwareQuickBase {activeModelAuthoritySource:"committed_assignment";assignmentPointerSha256:string;assignmentId:string;assignmentCommitSha256:string}
export interface HistoricalProfileFallbackQuickForecastJob extends AssignmentAwareQuickBase {activeModelAuthoritySource:"historical_profile_fallback_pending_explicit_bootstrap";historicalProfileSha256:string}
export type AssignmentAwareQuickForecastJob=CommittedAssignmentQuickForecastJob|HistoricalProfileFallbackQuickForecastJob;
export type QuickForecastJobRecord=HistoricalQuickForecastJob|AssignmentAwareQuickForecastJob;

export type LifecycleAction="bootstrap_historical_profile"|"retain_current_model"|"promote_selected_model"|"rollback_previous_assignment"|"defer"|"reject";
export interface LifecycleAcknowledgements{manualActionAcknowledged:true;statisticalSufficiencyNotGovernedAcknowledged:true;materialWorseningNotClassifiedAcknowledged:true;evidenceDoesNotProveSuperiorityAcknowledged:true;quickCompatibleRandomForestOnlyAcknowledged:true}
interface LifecycleJobBase extends LifecycleAcknowledgements{schemaVersion:"1.0";jobKind:"model_lifecycle";jobId:string;lifecycleDecisionId:string;deploymentId:"dhaka_south";geography:{level:"city";id:"BGD-DHAKA-SOUTH";name:"Dhaka South"};workflowMode:"model_lifecycle";policyId:"RUNTIME.MODEL_LIFECYCLE.DECISION";policyVersion:"p2-v1";policySha256:string;action:LifecycleAction;operatorIdentifier:string;reason:string;expectedAssignmentPointerState:"absent"|"present";expectedAssignmentPointerSha256:string|null;status:RuntimeJobStatus;progress:string;createdAt:string;claimedAt:string|null;startedAt:string|null;updatedAt:string;completedAt:string|null;heartbeatAt:string|null;workerId:string|null;processId:number|null;timeoutSeconds:number;retryCount:0;error:{code:string;message:string;retryable:boolean}|null;committedLifecycleDecisionId:string|null}
export interface BootstrapLifecycleJob extends LifecycleJobBase{action:"bootstrap_historical_profile";expectedAssignmentPointerState:"absent";expectedAssignmentPointerSha256:null;expectedProfileSha256:string}
export interface PromotionLifecycleEvidence{expectedAssessmentCommitSha256:string;expectedDecisionCommitSha256:string;expectedAuthorizationCommitSha256:string;expectedApprovedForecastCommitSha256:string;expectedOutcomeCommitSha256:string;expectedMonitoringLatestSha256:string;expectedMonitoringSummarySha256:string;expectedMonitoringIncludedOutcomeSetSha256:string;expectedDegradationLatestSha256:string;expectedDegradationEvidenceCommitSha256:string;expectedDegradationEvidenceSha256:string}
export interface PromotionLifecycleJob extends LifecycleJobBase,PromotionLifecycleEvidence{action:"promote_selected_model"}
export interface VerifiedContextEvidence{evidenceContextStatus:"verified_monitoring_and_degradation";expectedMonitoringLatestSha256:string;expectedMonitoringSummarySha256:string;expectedMonitoringIncludedOutcomeSetSha256:string;expectedDegradationLatestSha256:string;expectedDegradationEvidenceCommitSha256:string;expectedDegradationEvidenceSha256:string}
export interface RetentionLifecycleJob extends LifecycleJobBase,VerifiedContextEvidence{action:"retain_current_model"}
export interface RollbackLifecycleJob extends LifecycleJobBase{action:"rollback_previous_assignment";expectedAssignmentPointerState:"present";expectedAssignmentPointerSha256:string}
export type DeferLifecycleJob=(LifecycleJobBase&{action:"defer";evidenceContextStatus:"explicit_no_evidence"})|(LifecycleJobBase&VerifiedContextEvidence&{action:"defer"});
export type RejectLifecycleJob=(LifecycleJobBase&VerifiedContextEvidence&{action:"reject"})|(LifecycleJobBase&{action:"reject";evidenceContextStatus:"verified_assessment_and_decision";expectedAssessmentCommitSha256:string;expectedDecisionCommitSha256:string});
export type ModelLifecycleJobRecord=BootstrapLifecycleJob|PromotionLifecycleJob|RetentionLifecycleJob|RollbackLifecycleJob|DeferLifecycleJob|RejectLifecycleJob;

export interface DatasetAssessmentJobRecord extends RuntimeJobBase {
  jobKind: "dataset_assessment";
  assessmentId: string;
  workflowMode: "assess_dataset";
  assessmentPolicyId: "RUNTIME.DATASET_ASSESSMENT.GOVERNANCE";
  assessmentPolicyVersion: "p1.4d-1-v1" | "p2-v1";
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

export interface ForecastObservationRequest {
  forecastRunId: string; expectedForecastCommitSha256: string; deploymentId: "dhaka_south";
  geography: { level: "city"; id: "BGD-DHAKA-SOUTH"; name: "Dhaka South" };
  targetColumn: "target_cases_next_2w"; forecastHorizonWeeks: 2; forecastTargetPeriod: string;
  observedRaw: number; observationSourceType: "synthetic_benchmark";
  observationSourceId: "dhaka_south_synthetic_benchmark"; observationRecordId: string;
  observationRecordedAt: string; limitationsAcknowledged: true;
}

interface ForecastOutcomeJobCommon {
  jobKind:"forecast_outcome"; jobId:string; outcomeId:string; forecastRunId:string;
  expectedForecastCommitSha256:string; observationPayloadSha256:string;
  observation:Omit<ForecastObservationRequest,"forecastRunId"|"expectedForecastCommitSha256">;
  operatorIdentifier:string; deploymentId:"dhaka_south"; workflowMode:"forecast_outcome_monitoring";
  policyId:"RUNTIME.FORECAST_OUTCOME.MONITORING"; policySha256:string;
  status:RuntimeJobStatus; progress:string; createdAt:string; claimedAt:string|null; startedAt:string|null; updatedAt:string;
  completedAt:string|null; heartbeatAt:string|null; workerId:string|null; processId:number|null; timeoutSeconds:number;
  retryCount:number; error:{code:string;message:string;retryable:boolean}|null; committedOutcomeId:string|null;
}
export type ForecastOutcomeJobRecord=(ForecastOutcomeJobCommon&{schemaVersion:"1.0";policyVersion:"p1.4g-v1"})|(ForecastOutcomeJobCommon&{schemaVersion:"2.0";policyVersion:"p2-v1"});

export type ForecastOutcomeSourceFamily="quick_forecast_p1"|"approved_forecast_p1"|"approved_forecast_p2";
export interface MonitoringBreakdown {identity:string;evaluatedForecastCount:number;cumulativeMAE:number;cumulativeRMSE:number;cumulativeBias:number}
export interface MonitoringSummary {
  schemaVersion:"1.0"|"2.0";deploymentId:"dhaka_south";policyId:"RUNTIME.FORECAST_OUTCOME.MONITORING";policyVersion:"p1.4g-v1"|"p2-v1";policySha256:string;
  evaluatedForecastCount:number;totalEligibleForecastCount:number;pendingOutcomeCount:number;cumulativeMAE:number;cumulativeRMSE:number;cumulativeBias:number;cumulativeMPE:number|null;cumulativeMAPE:number|null;
  percentageMetricEvaluatedCount:number;zeroObservedCount:number;empiricalRangeEvaluatedCount:number;empiricalRangeCoveredCount:number;empiricalCoverage:number|null;latestEvaluatedTargetPeriod:string;
  modelBreakdowns:MonitoringBreakdown[];forecastPolicyBreakdowns:MonitoringBreakdown[];uncertaintyStatusBreakdowns:MonitoringBreakdown[];sourceFamilyBreakdowns?:MonitoringBreakdown[];monitoringPolicyBreakdowns?:MonitoringBreakdown[];
  latestSourceEvidence?:{sourceFamily:ForecastOutcomeSourceFamily;modelId:string;trainingRowCount:number|null;plannedFoldCount:number|null;targetPeriod:string};outcomeSetSha256:string;limitations:string[];
}
export type MonitoringSummaryResponse={ok:true;pointer:Record<string,unknown>;summary:MonitoringSummary;latestOutcome:Record<string,unknown>}|RuntimeErrorResponse;

export interface DegradationEvidenceJobRecord{schemaVersion:"1.0";jobKind:"degradation_evidence";jobId:string;evidenceId:string;deploymentId:"dhaka_south";geography:{level:"city";id:"BGD-DHAKA-SOUTH";name:"Dhaka South"};workflowMode:"degradation_evidence";policyId:"RUNTIME.MODEL_DEGRADATION.EVIDENCE";policyVersion:"p2-v1";policySha256:string;expectedMonitoringLatestSha256:string;expectedMonitoringSummarySha256:string;expectedIncludedOutcomeSetSha256:string;evidenceOnlyAcknowledged:true;status:RuntimeJobStatus;progress:string;createdAt:string;claimedAt:string|null;startedAt:string|null;updatedAt:string;completedAt:string|null;heartbeatAt:string|null;workerId:string|null;processId:number|null;timeoutSeconds:number;retryCount:0;error:{code:string;message:string;retryable:boolean}|null;committedEvidenceId:string|null}
export type DegradationEvidenceState="computable_descriptive_evidence"|"insufficient_recent_outcomes"|"insufficient_reference_outcomes"|"window_size_not_governed"|"sample_sufficiency_not_governed"|"percentage_metric_unavailable"|"range_metric_unavailable"|"not_applicable_no_assessment_reference"|"limited_cross_population_comparability"|"forecast_value_basis_mismatch"|"identity_not_comparable"|"unknown_identity_rejected"|"evidence_integrity_failure";
export interface ModelDegradationAssessmentReference{referenceType:"committed_assessment";assessmentId:string;modelId:string;modelFamily:string;parameterSha256:string;plannedFoldCount:number;successfulFolds:number;failedFolds:0;observedOutcomeCount:number;assessmentMAE:number;observedMAE:number;maeDelta:number;maeRatio:number|null;assessmentRMSE:number;observedRMSE:number;rmseDelta:number;rmseRatio:number|null;comparabilityStatus:"limited_cross_population_comparability";forecastValueBasisStatus:"equivalent_no_clipping_observed"|"forecast_value_basis_mismatch";sampleSufficiencyStatus:"not_governed";materialWorseningStatus:"not_governed";lifecycleActionStatus:"prohibited_not_generated";selectedEvaluationPeriod:{start:string;end:string}}
export interface ModelDegradationCohort{cohortId:string;outcomeSetSha256:string;identity:{sourceFamily:ForecastOutcomeSourceFamily;modelId:string;modelFamily:string;parameterSha256:string;forecastPolicy:{policyId:string;policyVersion:string;policySha256:string};monitoringPolicy:{policyId:string;policyVersion:string;policySha256:string};uncertaintyStatus:string};outcomeCount:number;actualPopulation:{mae:number;rmse:number;signedBias:number;absoluteBias:number;mpe:number|null;mape:number|null;percentageEligibleCount:number;rangeEligibleCount:number;empiricalCoverage:number|null};trainingContext:{trainingRowCounts:number[];trainingPeriods:string[];variationRecorded:boolean};assessmentReferenceStatus:"computable_descriptive_evidence"|"not_applicable_no_assessment_reference";assessmentReferences:ModelDegradationAssessmentReference[];monitoringWindow:{status:"window_size_not_governed";windowOutcomeCount:null;metricsCalculated:false;sampleSufficiencyStatus:"not_governed"};warnings:string[]}
export interface ModelDegradationEvidence{schemaVersion:"1.0";evidenceId:string;deploymentId:"dhaka_south";degradationPolicy:{policyId:"RUNTIME.MODEL_DEGRADATION.EVIDENCE";policyVersion:"p2-v1";policySha256:string};monitoringPolicy:{policyId:"RUNTIME.FORECAST_OUTCOME.MONITORING";policyVersion:"p2-v1";policySha256:string};monitoringInput:{latestSha256:string;summarySha256:string;includedOutcomeSetSha256:string;verifiedOutcomeCount:number};evidenceStatus:"evidence_only";materialWorseningStatus:"not_governed";lifecycleActionStatus:"prohibited_not_generated";cohorts:ModelDegradationCohort[];includedCohortSetSha256:string;generatedAt:string;limitations:string[]}
export interface ModelDegradationSummary{schemaVersion:"1.0";evidenceId:string;policyId:"RUNTIME.MODEL_DEGRADATION.EVIDENCE";policyVersion:"p2-v1";policySha256:string;verifiedOutcomeCount:number;cohortCount:number;assessmentReferenceDimensionCount:number;computableDescriptiveDimensionCount:number;insufficientEvidenceDimensionCount:number;windowSizeNotGovernedDimensionCount:number;percentageUnavailableDimensionCount:number;rangeUnavailableDimensionCount:number;sourceFamilyCounts:Record<string,number>;modelCounts:Record<string,number>;policyCounts:Record<string,number>;latestTargetPeriod:string;includedCohortSetSha256:string;includedOutcomeSetSha256:string;evidenceStatus:"evidence_only";materialWorseningStatus:"not_governed";lifecycleActionStatus:"prohibited_not_generated"}
export type ModelDegradationResponse={ok:true;pointer:Record<string,unknown>;commit:Record<string,unknown>;evidence:ModelDegradationEvidence;summary:ModelDegradationSummary}|RuntimeErrorResponse;

export interface ModelLifecyclePolicy{schema_version:"1.0";policy_id:"RUNTIME.MODEL_LIFECYCLE.DECISION";policy_version:"p2-v1";policy_status:"active";policy_sha256:string;policy_hash_method:"sha256_canonical_json_excluding_policy_sha256";deployment_id:"dhaka_south";geography:{level:"city";id:"BGD-DHAKA-SOUTH";name:"Dhaka South"};target:"target_cases_next_2w";forecast_horizon_weeks:2;accepted_policies:{assessment:{policy_id:"RUNTIME.DATASET_ASSESSMENT.GOVERNANCE";policy_version:"p2-v1";policy_sha256:string};decision:{policy_id:"RUNTIME.INTERNAL_ONE_RUN_MODEL_DECISION";policy_version:"p2-v1";policy_sha256:string};monitoring:{policy_id:"RUNTIME.FORECAST_OUTCOME.MONITORING";policy_version:"p2-v1";policy_sha256:string};degradation:{policy_id:"RUNTIME.MODEL_DEGRADATION.EVIDENCE";policy_version:"p2-v1";policy_sha256:string};quick_forecast:{policy_id:"RUNTIME.QUICK_FORECAST.COMPATIBILITY";policy_version:"p1.4f-v1";policy_sha256:string}};candidate_registry_sha256:string;feature_order_sha256:string;historical_profile_raw_sha256:string;permitted_active_model:{model_id:"random_forest";model_family:"RandomForestRegressor";parameter_sha256:string};allowed_actions:LifecycleAction[];automaticPromotionAllowed:false;automaticRollbackAllowed:false;automaticRetentionAllowed:false;thresholdBasedActionAllowed:false;operatorDecisionRequired:true;arbitraryModelSelectionAllowed:false;arbitraryRollbackTargetAllowed:false;baselineAssignmentAllowed:false;profileMutationAllowed:false;oneActiveAssignmentPointer:true;rollbackOnlyToVerifiedPriorAssignment:true;unknownIdentityFallbackAllowed:false;materialWorseningClassificationRequired:false;lifecycleRecommendationFromDegradationEvidenceAllowed:false;nonRandomForestActivationAllowed:false;activeQuickForecastPolicyRequired:true;assignmentHistoryMutationAllowed:false}
interface LifecycleDecisionBase extends LifecycleAcknowledgements{schemaVersion:"1.0";lifecycleDecisionId:string;jobId:string;deploymentId:"dhaka_south";geography:{level:"city";id:"BGD-DHAKA-SOUTH";name:"Dhaka South"};target:"target_cases_next_2w";forecastHorizonWeeks:2;policyId:"RUNTIME.MODEL_LIFECYCLE.DECISION";policyVersion:"p2-v1";policySha256:string;action:LifecycleAction;operatorType:"trusted_internal";operatorIdentifier:string;reason:string;expectedAssignmentPointerState:"absent"|"present";expectedAssignmentPointerSha256:string|null;activeModelIdBefore:"random_forest";activeModelFamilyBefore:"RandomForestRegressor";activeParameterSha256Before:string;activeAuthoritySourceBefore:"committed_assignment"|"historical_profile_fallback_pending_explicit_bootstrap";activeAuthoritySnapshotSha256Before:string;priorAssignmentId:string|null;priorAssignmentCommitSha256:string|null;resultingAssignmentId:string|null;modelIdentityChanged:false;materialWorseningStatus:"not_governed";statisticalSufficiencyStatus:"not_governed";automaticAction:false;createdAt:string;decisionStatus:"committed"}
export interface CommittedPromotionEvidence{assessmentCommitSha256:string;decisionCommitSha256:string;authorizationCommitSha256:string;approvedForecastCommitSha256:string;outcomeCommitSha256:string;monitoringLatestSha256:string;monitoringSummarySha256:string;monitoringIncludedOutcomeSetSha256:string;degradationLatestSha256:string;degradationEvidenceCommitSha256:string;degradationEvidenceSha256:string}
export interface CommittedContextEvidence{evidenceContextStatus:"verified_monitoring_and_degradation";monitoringLatestSha256:string;monitoringSummarySha256:string;monitoringIncludedOutcomeSetSha256:string;degradationLatestSha256:string;degradationEvidenceCommitSha256:string;degradationEvidenceSha256:string}
export interface BootstrapLifecycleDecision extends LifecycleDecisionBase{action:"bootstrap_historical_profile";profileSha256:string;resultingAssignmentId:string}
export interface PromotionLifecycleDecision extends LifecycleDecisionBase,CommittedPromotionEvidence{action:"promote_selected_model";resultingAssignmentId:string;assessmentId:string;sourceDecisionId:string;authorizationId:string;approvedForecastRunId:string;outcomeId:string;degradationEvidenceId:string;assessmentReferenceCohortId:string;assessmentReferenceDimensionId:string;selectedModelId:"random_forest";selectedModelFamily:"RandomForestRegressor";selectedParameterSha256:string;candidateRegistrySha256:string;featureOrderSha256:string}
export interface RetentionLifecycleDecision extends LifecycleDecisionBase,CommittedContextEvidence{action:"retain_current_model";resultingAssignmentId:null}
export interface RollbackLifecycleDecision extends LifecycleDecisionBase{action:"rollback_previous_assignment";resultingAssignmentId:string;rollbackSourceAssignmentId:string;rollbackSourceAssignmentCommitSha256:string}
export type DeferLifecycleDecision=(LifecycleDecisionBase&{action:"defer";resultingAssignmentId:null;evidenceContextStatus:"explicit_no_evidence"})|(LifecycleDecisionBase&CommittedContextEvidence&{action:"defer";resultingAssignmentId:null});
export type RejectLifecycleDecision=(LifecycleDecisionBase&CommittedContextEvidence&{action:"reject";resultingAssignmentId:null})|(LifecycleDecisionBase&{action:"reject";resultingAssignmentId:null;evidenceContextStatus:"verified_assessment_and_decision";assessmentCommitSha256:string;decisionCommitSha256:string});
export type LifecycleDecision=BootstrapLifecycleDecision|PromotionLifecycleDecision|RetentionLifecycleDecision|RollbackLifecycleDecision|DeferLifecycleDecision|RejectLifecycleDecision;
interface LifecycleDecisionCommitBase{schemaVersion:"1.0";lifecycleDecisionId:string;jobId:string;policyId:"RUNTIME.MODEL_LIFECYCLE.DECISION";policyVersion:"p2-v1";policySha256:string;action:LifecycleAction;inputAssignmentPointerState:"absent"|"present";inputAssignmentPointerSha256:string|null;lifecycleDecisionSha256:string;operatorIdentitySource:"server_configuration";committedAt:string;status:"committed";profileModified:false;forecastLatestModified:false;monitoringLatestModified:false;degradationLatestModified:false;authorizationModified:false;automaticActionProduced:false}
export type LifecycleDecisionCommit=LifecycleDecisionCommitBase&({action:"bootstrap_historical_profile";profileSha256:string}|({action:"promote_selected_model"}&CommittedPromotionEvidence)|({action:"retain_current_model"|"reject"}&CommittedContextEvidence)|{action:"reject";evidenceContextStatus:"verified_assessment_and_decision";assessmentCommitSha256:string;decisionCommitSha256:string}|{action:"rollback_previous_assignment";rollbackSourceAssignmentId:string;rollbackSourceAssignmentCommitSha256:string}|{action:"defer";evidenceContextStatus:"explicit_no_evidence"}|({action:"defer"}&CommittedContextEvidence));
interface ModelAssignmentBase{schemaVersion:"1.0";assignmentId:string;assignmentReason:"historical_profile_bootstrap"|"manual_selected_model_promotion"|"controlled_previous_assignment_rollback";deploymentId:"dhaka_south";geography:{level:"city";id:"BGD-DHAKA-SOUTH";name:"Dhaka South"};target:"target_cases_next_2w";forecastHorizonWeeks:2;policyId:"RUNTIME.MODEL_LIFECYCLE.DECISION";policyVersion:"p2-v1";policySha256:string;lifecycleDecisionId:string;lifecycleDecisionCommitSha256:string;assignmentAction:"bootstrap"|"promote"|"rollback";assignedModelId:"random_forest";modelFamily:"RandomForestRegressor";parameterSha256:string;featureOrderSha256:string;candidateRegistrySha256:string;quickForecastPolicyId:"RUNTIME.QUICK_FORECAST.COMPATIBILITY";quickForecastPolicyVersion:"p1.4f-v1";quickForecastPolicySha256:string;quickCompatibilityStatus:"compatible_exact_governed_random_forest";priorAssignmentId:string|null;priorAssignmentCommitSha256:string|null;effectiveAt:string;assignmentStatus:"committed";modelQualificationStatus:"not_governed";materialWorseningStatus:"not_governed";statisticalSufficiencyStatus:"not_governed";automaticAction:false;modelIdentityChanged:false}
export interface BootstrapModelAssignment extends ModelAssignmentBase{assignmentAction:"bootstrap";assignmentReason:"historical_profile_bootstrap";priorAssignmentId:null;priorAssignmentCommitSha256:null;profileRawSha256:string}
export interface PromotionModelAssignment extends ModelAssignmentBase{assignmentAction:"promote";assignmentReason:"manual_selected_model_promotion";sourceAssessmentId:string;sourceAssessmentCommitSha256:string;sourceDecisionId:string;sourceDecisionArtifactSha256:string;sourceDecisionCommitSha256:string;sourceAuthorizationId:string;sourceAuthorizationRecordSha256:string;sourceAuthorizationCommitSha256:string;sourceAuthorizationConsumptionSha256:string;sourceApprovedForecastId:string;sourceApprovedForecastCommitSha256:string;sourceOutcomeId:string;sourceOutcomeCommitSha256:string;sourceMonitoringLatestSha256:string;sourceMonitoringSummarySha256:string;sourceMonitoringIncludedOutcomeSetSha256:string;sourceDegradationLatestSha256:string;sourceDegradationEvidenceId:string;sourceDegradationEvidenceCommitSha256:string;sourceDegradationEvidenceSha256:string;assessmentReferenceCohortId:string;assessmentReferenceDimensionId:string}
export interface RollbackModelAssignment extends ModelAssignmentBase{assignmentAction:"rollback";assignmentReason:"controlled_previous_assignment_rollback";priorAssignmentId:string;priorAssignmentCommitSha256:string;rollbackSourceAssignmentId:string;rollbackSourceAssignmentCommitSha256:string}
export type ModelAssignment=BootstrapModelAssignment|PromotionModelAssignment|RollbackModelAssignment;
interface ModelAssignmentCommitBase{schemaVersion:"1.0";assignmentId:string;assignmentAction:"bootstrap"|"promote"|"rollback";assignmentSha256:string;lifecycleDecisionId:string;lifecycleDecisionCommitSha256:string;priorPointerSha256:string|null;priorAssignmentId:string|null;priorAssignmentCommitSha256:string|null;assignedModelId:"random_forest";modelFamily:"RandomForestRegressor";parameterSha256:string;featureOrderSha256:string;candidateRegistrySha256:string;quickForecastPolicyId:"RUNTIME.QUICK_FORECAST.COMPATIBILITY";quickForecastPolicyVersion:"p1.4f-v1";quickForecastPolicySha256:string;publicationEligible:true;committedAt:string;status:"committed";profileModified:false;forecastLatestModified:false;monitoringLatestModified:false;degradationLatestModified:false;authorizationModified:false;automaticActionProduced:false}
export type ModelAssignmentCommit=ModelAssignmentCommitBase&({assignmentAction:"bootstrap";priorPointerSha256:null;priorAssignmentId:null;priorAssignmentCommitSha256:null;profileRawSha256:string}|{assignmentAction:"promote";sourceAssessmentCommitSha256:string;sourceDecisionArtifactSha256:string;sourceDecisionCommitSha256:string;sourceAuthorizationRecordSha256:string;sourceAuthorizationCommitSha256:string;sourceAuthorizationConsumptionSha256:string;sourceApprovedForecastCommitSha256:string;sourceOutcomeCommitSha256:string;sourceMonitoringLatestSha256:string;sourceMonitoringSummarySha256:string;sourceMonitoringIncludedOutcomeSetSha256:string;sourceDegradationLatestSha256:string;sourceDegradationEvidenceCommitSha256:string;sourceDegradationEvidenceSha256:string}|{assignmentAction:"rollback";priorPointerSha256:string;priorAssignmentId:string;priorAssignmentCommitSha256:string;rollbackSourceAssignmentId:string;rollbackSourceAssignmentCommitSha256:string});
interface ModelAssignmentLatestBase{schemaVersion:"1.0";deploymentId:"dhaka_south";assignmentId:string;assignedModelId:"random_forest";modelFamily:"RandomForestRegressor";parameterSha256:string;featureOrderSha256:string;candidateRegistrySha256:string;policyId:"RUNTIME.MODEL_LIFECYCLE.DECISION";policyVersion:"p2-v1";policySha256:string;lifecycleDecisionId:string;lifecycleDecisionCommitSha256:string;assignmentCommitSha256:string;assignmentPath:string;assignmentSha256:string;lifecycleDecisionPath:string;lifecycleDecisionSha256:string;publishedAt:string;activeModelAuthority:"committed_assignment";automaticAction:false}
export type ModelAssignmentLatest=(ModelAssignmentLatestBase&{assignmentAction:"bootstrap";priorAssignmentId:null;priorAssignmentCommitSha256:null})|(ModelAssignmentLatestBase&{assignmentAction:"promote";priorAssignmentId:string|null;priorAssignmentCommitSha256:string|null})|(ModelAssignmentLatestBase&{assignmentAction:"rollback";priorAssignmentId:string;priorAssignmentCommitSha256:string});
export type HistoricalProfileActiveModelAuthority={authoritySource:"historical_profile_fallback_pending_explicit_bootstrap";authoritySnapshotSha256:string;assignmentPointerSha256:null;assignmentId:null;assignmentCommitSha256:null;modelId:"random_forest";modelFamily:"RandomForestRegressor";parameterSha256:string;featureOrderSha256:string;candidateRegistrySha256:string;quickPolicyId:"RUNTIME.QUICK_FORECAST.COMPATIBILITY";quickPolicyVersion:"p1.4f-v1";quickPolicySha256:string;lifecyclePolicyId:"RUNTIME.MODEL_LIFECYCLE.DECISION";lifecyclePolicyVersion:"p2-v1";lifecyclePolicySha256:string;profileSha256:string;bootstrapRequired:true;quickForecastCompatible:true};
export type CommittedAssignmentActiveModelAuthority={authoritySource:"committed_assignment";authoritySnapshotSha256:string;assignmentPointerSha256:string;assignmentId:string;assignmentCommitSha256:string;assignmentAction:"bootstrap"|"promote"|"rollback";effectiveAt:string;priorAssignmentId:string|null;modelId:"random_forest";modelFamily:"RandomForestRegressor";parameterSha256:string;featureOrderSha256:string;candidateRegistrySha256:string;quickPolicyId:"RUNTIME.QUICK_FORECAST.COMPATIBILITY";quickPolicyVersion:"p1.4f-v1";quickPolicySha256:string;lifecyclePolicyId:"RUNTIME.MODEL_LIFECYCLE.DECISION";lifecyclePolicyVersion:"p2-v1";lifecyclePolicySha256:string;profileSha256:null;bootstrapRequired:false;quickForecastCompatible:true};
export type ActiveModelAuthority=HistoricalProfileActiveModelAuthority|CommittedAssignmentActiveModelAuthority;
export type ModelLifecycleJobStatusResponse={ok:true;jobKind:"model_lifecycle";jobId:string;lifecycleDecisionId:string;workflowMode:"model_lifecycle";action:LifecycleAction;status:RuntimeJobStatus;progress:string;createdAt:string;startedAt:string|null;updatedAt:string;completedAt:string|null;retryable:false;error:RuntimeJobRecord["error"];committedLifecycleDecisionId:string|null};
export type ModelLifecycleResponse={ok:true;authority:ActiveModelAuthority;history:Array<{lifecycleDecisionId:string;action:LifecycleAction;createdAt:string;modelIdentityChanged:boolean;assignmentProduced:boolean}>;rollbackAvailable:boolean;humanGoverned:true;automaticActionAllowed:false;materialWorseningStatus:"not_governed";statisticalSufficiencyStatus:"not_governed";modelQualificationStatus:"not_governed"}|RuntimeErrorResponse;

export type RuntimeJobRecord = QuickForecastJobRecord | DatasetAssessmentJobRecord | ApprovedForecastJobRecord | ForecastOutcomeJobRecord | DegradationEvidenceJobRecord | ModelLifecycleJobRecord;

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
  | ({ ok:true; jobKind:"forecast_outcome"; jobId:string; outcomeId:string; workflowMode:"forecast_outcome_monitoring"; status:RuntimeJobStatus; progress:string; createdAt:string; startedAt:string|null; updatedAt:string; completedAt:string|null; retryable:boolean; error:RuntimeJobRecord["error"]; committedOutcomeId:string|null })
  | ({ok:true;jobKind:"degradation_evidence";jobId:string;evidenceId:string;workflowMode:"degradation_evidence";status:RuntimeJobStatus;progress:string;createdAt:string;startedAt:string|null;updatedAt:string;completedAt:string|null;retryable:false;error:RuntimeJobRecord["error"];committedEvidenceId:string|null})
  | ({ok:true;jobKind:"model_lifecycle";jobId:string;lifecycleDecisionId:string;workflowMode:"model_lifecycle";action:LifecycleAction;status:RuntimeJobStatus;progress:string;createdAt:string;startedAt:string|null;updatedAt:string;completedAt:string|null;retryable:false;error:RuntimeJobRecord["error"];committedLifecycleDecisionId:string|null})
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

export interface AssessmentCandidateProjection extends AssessmentCandidateSummary {
  displayRank: number | null;
  modelFamily: string;
  technicalWinner: boolean;
  currentApprovedModel: boolean;
  deployableForOneRun: boolean;
}

export interface AssessmentDecisionWorkflowProjection {
  decisionId: string;
  outcome: DecisionChoice;
  decisionStatus: string;
  selectedModelId: RuntimeCandidateId | null;
  forecastAuthorized: boolean;
  authorizationId: string | null;
  authorizationStatus: "not_authorized" | "authorization_incomplete" | "available" | "reserved" | "consumed";
  forecastStatus: "not_authorized" | "authorized" | "reserved" | "committed";
  committedRunId: string | null;
  decisionCommitSha256: string;
  createdAt: string;
}

export interface AssessmentWorkflowProjection {
  assessmentId: string;
  assessmentPolicy: { policyId: string; policyVersion: string; policySha256: string };
  target: "target_cases_next_2w";
  horizonWeeks: 2;
  currentApprovedModelId: "random_forest";
  currentApprovedModelFamily: string;
  candidates: AssessmentCandidateProjection[];
  technicalWinnerModelId: RuntimeCandidateId | null;
  technicalWinnerDeployable: boolean;
  recommendationStatus: "evidence_only" | "no_recommendation";
  decisionCompatibilityStatus:
    | "phase1_decision_policy_available"
    | "phase2_decision_policy_available"
    | "phase2_decision_policy_not_yet_available";
  decision: AssessmentDecisionWorkflowProjection | null;
}

export interface DatasetAssessmentResultSuccess {
  ok: true;
  schemaVersion: "1.0" | "2.0";
  assessmentId: string;
  jobId: string;
  datasetId: string;
  deploymentId: string;
  sourceType: "uploaded";
  acceptedPeriod: { start: string; end: string };
  labelledRows: number;
  availableFoldCount: number;
  committedAt: string;
  assessmentStatus: "assessment_complete";
  approvalStatus: "approval_pending";
  adoptionStatus: "not_adopted";
  foldPolicy: { policyId: string; policyVersion: string; plannedFoldCount: number; minimumFoldCount: number; maximumFoldCount: number; foldCapApplied: boolean; selectedValidationStartIndex: number; selectedValidationEndIndex: number; selectedEvaluationPeriod: {start:string;end:string}; initialTrainingRows: 104; embargoRows: 1; validationRowsPerFold: 1; stepSizeWeeks: 1; horizonWeeks: 2; samePlanForAllCandidates: true };
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
  decisionCompatibilityStatus: "phase1_decision_policy_available" | "phase2_decision_policy_not_yet_available";
  limitations: string[];
  evidenceHashes: { rollingValidationSha256: string; candidateComparisonSha256: string; recommendationSha256: string };
  provenance: { validationRecordSha256: string; assessmentPolicySha256: string; candidateRegistrySha256: string; featureOrderSha256: string };
  integrity: { assessmentSummarySha256: string; assessmentCommitSha256: string };
  workflow: AssessmentWorkflowProjection;
}

export type DatasetAssessmentResponse = DatasetAssessmentResultSuccess | RuntimeErrorResponse;

export type DecisionChoice = "approve_technical_winner" | "approve_eligible_non_winner" | "keep_current_model" | "defer" | "reject_assessment";
export interface RecordDecisionRequest {decision:DecisionChoice;reason:string;expectedAssessmentSummarySha256:string;selectedModelId?:string;technicalWinnerNotSelectedAcknowledged?:true;uncertaintyLimitationsAcknowledged?:true}
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
