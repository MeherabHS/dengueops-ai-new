// ─── Forecast & Uncertainty ────────────────────────────────────────────────

export type RiskLevel = "Low" | "Moderate" | "High" | "Critical";
export type DeploymentGate = "benchmark_only" | "research_candidate" | "locally_backtested" | "expert_reviewed" | "institution_approved" | "shadow_validated" | "operational_advisory";
export type DeploymentProfileDataMode = "synthetic_capability_demonstration" | "research_candidate" | "locally_calibrated_deployment" | "institution_approved_deployment";
export type ObservedDataMode = "synthetic" | "real" | "mixed";

export interface MaturityStatements {
  maturity: string;
  demonstration: string;
  prohibited_claim: string;
  notification: string;
}

export interface DeprecatedCompatibilityFields {
  debt_id: "TD-P03A-LEGACY-RISK-FIELDS";
  status: "open";
  legacy_fields: ["risk_level", "risk_score", "recommendations"];
  canonical_fields: ["forecast_growth_category", "experimental_growth_score", "planning_priority_tier", "planning_suggestions"];
  runtime_behavior: "preserved_for_backward_compatibility";
  deprecated: true;
}

export interface FormulaGovernance {
  formula_registry_version: string;
  formula_registry_sha256: string;
  formula_ids_used: string[];
  deployment_gate: DeploymentGate;
  formula_validation_status: string;
  formula_policy?: Record<string, {
    version: string;
    name: string;
    category: string;
    evidence_status: string;
    approval_status: string;
    deployment_gate: DeploymentGate;
    parameters: Record<string, string | number | number[]>;
  }>;
}

export interface ArtifactProvenance {
  run_id: string;
  manifest_path: string;
  manifest_sha256: string;
  case_source: string;
  climate_source: string;
  operational_source: string;
  source_classes: { cases: string; climate: string; operational: string };
  forecast_geography: { level: string; id: string; name: string };
  validation_status: "passed";
  warnings: string[];
  overrides: string[];
  deployment_profile_id?: string;
  deployment_profile_schema_version?: string;
  deployment_profile_sha256?: string;
  deployment_profile_status?: "draft" | "active" | "suspended" | "retired" | "superseded";
  deployment_profile_data_mode?: DeploymentProfileDataMode;
  observed_data_mode?: ObservedDataMode;
  evidence_registry_schema_version?: string;
  evidence_registry_version?: string;
  evidence_registry_sha256?: string;
  formula_registry_version?: string;
  formula_registry_sha256?: string;
  model_card_id?: string;
  model_card_version?: string;
  candidate_registry_sha256?: string;
  active_model_id?: "random_forest";
  active_model_parameters_sha256?: string;
  adoption_status?: "adopted_p1.2b";
  adoption_policy_version?: "p1.2b-v1";
}

export interface DeploymentProfileMetadata {
  profile_id: string;
  profile_status: string;
  demonstration_status: DeploymentProfileDataMode;
  maturity_statement: string;
  demonstration_statement: string;
  prohibited_claim: string;
  notification_wording: string;
  deployment_gate: DeploymentGate;
  evidence_status: string;
  approval_status: string;
}

export interface UncertaintyScenario {
  forecast_cases: number;
  growth_factor: number;
  // TD-P03A-LEGACY-RISK-FIELDS: compatibility only; canonical fields follow.
  risk_score: number;
  risk_level: RiskLevel;
  experimental_growth_score?: number;
  forecast_growth_category?: string;
}

export interface ForecastOutput extends FormulaGovernance {
  provenance: ArtifactProvenance;
  data_mode: "synthetic" | "real" | "mixed";
  target: string;
  forecast_origin: { epi_year: number; epi_week: number };
  training_cutoff: { epi_year: number; epi_week: number };
  forecast_id: number;
  date_generated: string;
  latest_known_epi_year: number;
  latest_known_epi_week: number;
  latest_observed_cases: number;
  training_cutoff_epi_year: number;
  training_cutoff_epi_week: number;
  target_epi_year: number;
  target_epi_week: number;
  horizon_days: number;
  city: string;
  forecast_cases: number;
  growth_factor: number;
  // TD-P03A-LEGACY-RISK-FIELDS: compatibility only; not authoritative.
  risk_score: number;
  risk_level: RiskLevel;
  experimental_growth_score: number;
  forecast_growth_category: string;
  model_name: string;
  active_model_id: "random_forest";
  current_forecast_model: "random_forest";
  model_family: "RandomForestRegressor";
  estimator_library: "scikit-learn";
  estimator_library_version: string;
  adopted_model_parameters_sha256: string;
  candidate_registry_sha256: string;
  comparison_artifact_sha256: string;
  comparison_selected_model: "random_forest";
  adoption_status: "adopted_p1.2b";
  adoption_policy_version: "p1.2b-v1";
  raw_prediction: number;
  published_prediction: number;
  clipping_applied: boolean;
  reporting_rounding_policy: string;
  reference_cases_4w_rolling?: number;
  uncertainty_status: "temporally_evaluated_synthetic_empirical_range";
  forecast_uncertainty: DashboardSummaryUncertainty;
  preparedness_scenario_method: DashboardSummaryUncertaintyMethod;
  preparedness_scenarios: {
    best_case: UncertaintyScenario;
    expected_case: UncertaintyScenario;
    worst_case: UncertaintyScenario;
  };
  uncertainty_scenarios: {
    best_case: UncertaintyScenario;
    expected_case: UncertaintyScenario;
    worst_case: UncertaintyScenario;
  };
}

// ─── Validation ────────────────────────────────────────────────────────────

export interface BaselineResult {
  model: string;
  mae: number;
  rmse: number;
  mape: number;
}

export interface ActualVsPredicted {
  epi_week: number;
  actual: number;
  predicted: number;
  lower_bound: number;
  upper_bound: number;
}

export interface SeasonalityDriftPoint {
  year: number;
  peak_week: number;
  peak_cases: number;
}

export interface ValidationMetrics {
  model_name: string;
  test_period: string;
  mae: number;
  rmse: number;
  mape: number;
  r2: number;
  n_test_weeks: number;
  baseline_results: BaselineResult[];
  actual_vs_predicted: ActualVsPredicted[];
  seasonality_drift: SeasonalityDriftPoint[];
  note: string;
}

// ─── Feature Importance ────────────────────────────────────────────────────

export interface FeatureDiagnosticRecord {
  feature_name: string;
  formula_id: string;
  feature_index: number;
  impurity_importance: number;
  permutation_mean: number;
  permutation_standard_deviation: number;
  rank_by_impurity: number;
  rank_by_permutation: number;
  rank_disagreement: boolean;
  permutation_is_negative: boolean;
  permutation_is_zero: boolean;
}

export interface GeneratedFeatureDiagnostics {
  status: "generated";
  title: string;
  formula_id: "EVIDENCE.FEATURE_IMPORTANCE";
  estimator_role: "selected_model_chronological_holdout_validation_instance";
  model_id: string;
  model_version: string;
  methods: {
    primary: { id: string; label: string; scoring: "neg_mean_absolute_error"; repeats: 20; random_state: 42 };
    secondary: { id: string; label: string };
  };
  evaluation_split: "legacy_final_chronological_20_percent";
  validation_period: { start: { epi_year: number; epi_week: number }; end: { epi_year: number; epi_week: number } };
  stability_status: "not_evaluated_across_temporal_folds";
  feature_ranking: FeatureDiagnosticRecord[];
  non_causal_warning: string;
  split_warning: string;
  stability_warning: string;
  synthetic_warning: string;
  negative_importance_policy: string;
  correlated_feature_warning: string;
  causal_interpretation_allowed: false;
  provenance: ArtifactProvenance;
}

export interface UnavailableFeatureDiagnostics {
  status: "not_generated";
  message: string;
  formula_id: "EVIDENCE.FEATURE_IMPORTANCE";
}

export type FeatureDiagnostics = GeneratedFeatureDiagnostics | UnavailableFeatureDiagnostics;

// ─── Zones ─────────────────────────────────────────────────────────────────

export type ZoneProfile = "High-density informal" | "Dense commercial-residential" | "Mixed residential-institutional" | "High-density transport hub" | "Dense industrial-residential";

export interface Zone {
  zone_id: string;
  zone_name: string;
  city: string;
  population_share: number;
  density_weight: number;
  facility_pressure_weight: number;
  mobility_corridor_weight: number;
  vulnerability_weight: number;
  exposure_index: number;
  current_anomaly_adjustment: number;
  profile: ZoneProfile;
}

// ─── Facilities ────────────────────────────────────────────────────────────

export type FacilityAnchorType = "real_public_hospital_anchor" | "synthetic_local_response_unit";
export type BedCapacitySource = "public_reference_anchor" | "synthetic_demo_assumption";

export interface Facility {
  facility_id: string;
  zone_id: string;
  facility_name: string;
  facility_type: string;
  facility_anchor_type: FacilityAnchorType;
  /** Total general bed count. Public reference for real anchors; synthetic assumption for local units. */
  general_bed_capacity: number;
  /** Synthetic dengue-simulation bed subset — does NOT claim real dengue ward capacity. */
  dengue_bed_capacity_demo: number;
  /** Synthetic demo occupancy figure only. */
  occupied_dengue_beds_demo: number;
  avg_length_of_stay: number;
  /** Synthetic daily throughput used for load-share allocation only. */
  baseline_daily_dengue_cases_demo: number;
  bed_capacity_source: BedCapacitySource;
  readiness_data_status: string;
  inventory_data_status: string;
  notes?: string;
}

// ─── Inventory ─────────────────────────────────────────────────────────────

export type InventoryItem = "NS1/RDT Kit" | "IV Fluid (500ml)";

export interface Inventory {
  inventory_id: string;
  facility_id: string;
  item_name: InventoryItem;
  current_stock: number;
  baseline_daily_consumption: number;
  reorder_threshold_days: number;
}

// ─── Directives ────────────────────────────────────────────────────────────

/** alert_level matches the Python output: "Critical" | "Warning" (capitalised) */
export type AlertLevel = "Critical" | "Warning";

export interface InventoryAlert {
  item_name: string;
  sdh_expected: number;
  threshold_days: number;
  alert_level: AlertLevel;
  message: string;
}

export interface Directive {
  forecast_id: number;
  target_epi_year: number;
  target_epi_week: number;
  // Zone fields
  zone_id: string;
  zone_name: string;
  zone_profile: string;
  // Facility fields
  facility_id: string;
  facility_name: string;
  facility_type: string;
  facility_anchor_type: string;
  data_status: string;
  // Exposure
  exposure_index: number;
  adjusted_exposure: number;
  normalized_exposure: number;
  facility_load_share: number;
  // Facility-level case allocations
  allocated_cases_best: number;
  allocated_cases_expected: number;
  allocated_cases_worst: number;
  // Zone-level case totals (for zone summary tables)
  zone_allocated_cases_best: number;
  zone_allocated_cases_expected: number;
  zone_allocated_cases_worst: number;
  // Priority (zone-level, same for all facilities in zone)
  priority_score: number;
  raw_priority_score: number;
  priority_category: string;
  planning_priority_tier?: string;
  planning_priority_label?: string;
  // Bed load (facility-level)
  projected_bed_load_best: number;
  projected_bed_load_expected: number;
  projected_bed_load_worst: number;
  // Bed gap — POSITIVE value means deficit (0 = no gap)
  bed_gap_best: number;
  bed_gap_expected: number;
  bed_gap_worst: number;
  /** Total general bed count (public reference for real anchors, synthetic for local units) */
  general_bed_capacity: number | null;
  /** Synthetic dengue-simulation bed subset used for bed pressure calculations */
  dengue_bed_capacity_demo: number;
  /** Synthetic demo occupancy figure */
  occupied_dengue_beds_demo: number;
  avg_length_of_stay: number;
  // SDH consumables (null if no inventory for that item type)
  sdh_ns1_best: number | null;
  sdh_ns1_expected: number | null;
  sdh_ns1_worst: number | null;
  sdh_iv_fluid_best: number | null;
  sdh_iv_fluid_expected: number | null;
  sdh_iv_fluid_worst: number | null;
  // Alerts and recommendations
  inventory_alerts: InventoryAlert[];
  // TD-P03A-LEGACY-RISK-FIELDS: compatibility only; use planning_suggestions.
  recommendations: string[];
  planning_suggestions?: Array<{
    label: string;
    type: "Simulated planning suggestion";
    formula_ids: string[];
    deployment_gate: DeploymentGate;
    approval_status: string;
    disclaimer: string;
  }>;
  admission_fraction?: number;
  bed_demand_label?: string;
  generation_timestamp: string;
}

// ─── Dashboard Summary (from analytics/dashboard_exporter.py) ──────────────

export interface DashboardSummaryHeadlineMetrics {
  forecast_cases: number;
  growth_factor: number;
  risk_level: RiskLevel;
  risk_score: number;
  target_epi_week: number;
  target_epi_year: number;
  highest_priority_zone: string;
  highest_pressure_facility: string;
  critical_supply_alerts: number;
  facilities_with_expected_bed_gap: number;
  total_facilities: number;
  total_public_government_anchors: number;
  critical_priority_zones: number;
}

export interface DashboardSummaryUncertaintyScenario {
  label: string;
  forecast_cases: number;
  growth_factor: number;
  risk_score: number;
  risk_level: RiskLevel;
}

export interface DashboardSummaryUncertaintyMethod {
  type: string;
  source: string;
  model: string;
  rmse: number;
  uncertainty_pct: number;
  note: string;
  status?: string;
  calibrated?: false;
  is_prediction_interval?: false;
}

export interface DashboardSummaryUncertainty {
  method_id: "prequential_expanding_absolute_residual_quantile";
  method_version: "p1.3-v1";
  uncertainty_status: "temporally_evaluated_synthetic_empirical_range";
  point_forecast_raw: number;
  interval_lower_raw: number;
  interval_upper_raw: number;
  point_forecast_reported: number;
  interval_lower_reported: number;
  interval_upper_reported: number;
  lower_clipping_applied: boolean;
  nominal_coverage: 0.9;
  observed_historical_coverage: number;
  evaluated_fold_count: 48;
  covered_fold_count?: number;
  calibration_warmup_fold_count?: number;
  lower_miss_count?: number;
  upper_miss_count?: number;
  interval_width_summary?: {
    average_interval_width: number;
    median_interval_width: number;
    minimum_interval_width: number;
    maximum_interval_width: number;
  };
  average_interval_width?: number;
  median_interval_width?: number;
  minimum_interval_width?: number;
  maximum_interval_width?: number;
  uncertainty_method?: string;
  uncertainty_method_version?: string;
  residual_source_artifact_path?: string;
  uncertainty_artifact_path: "data/forecast_uncertainty.json";
  uncertainty_artifact_sha256: string;
  residual_source_artifact_sha256: string;
  active_model_id: "random_forest";
  active_model_parameters_sha256: string;
  is_prediction_interval: false;
  calibrated_on_synthetic_data: true;
  limitations: string[];
  method_label?: string;
  range_label?: string;
  method_note: string;
}

export interface DashboardPreparednessScenarios {
  best_case: DashboardSummaryUncertaintyScenario;
  expected_case: DashboardSummaryUncertaintyScenario;
  worst_case: DashboardSummaryUncertaintyScenario;
  method: DashboardSummaryUncertaintyMethod;
  status: "legacy_rf_rmse_planning_sensitivity_separate_from_forecast_uncertainty";
}

export interface DashboardSummaryModelEvidence {
  best_model: string;
  best_model_display: string;
  best_model_reason: string;
  validation_design: string;
  train_rows: number;
  test_rows: number;
  active_model_mae: number;
  active_model_rmse: number;
  active_rolling_metrics_source: "candidate_model_comparison.json";
  legacy_gbr_holdout: { mae: number; rmse: number; status: "historical_compatibility_only" };
  mae_reduction_vs_naive_pct: number;
  mae_reduction_vs_moving_average_pct: number;
  disclaimer: string;
}

export interface RollingAggregateMetrics {
  fold_count: number; mae: number; rmse: number; mape: number | null; wape: number | null;
  median_absolute_error: number; absolute_error_standard_deviation: number;
}
export interface RollingFoldRecord {
  fold_id: string; fold_index: number; train_start: string; train_end: string; embargo_period: string;
  origin_period: string; target_period: string; train_rows: number; validation_rows: number;
  predictions: Record<string, { prediction: number; actual: number; absolute_error: number }>;
}
export interface RollingValidationSummary {
  primary_validation: false; evidence_status: "historical_compatibility_only"; active_model_evidence: false;
  validation_method: "expanding_window_rolling_origin"; fold_count: number;
  initial_training_window: number; horizon_weeks: number; step_weeks: number; label_availability_policy: string;
  aggregate_metrics: Record<string, RollingAggregateMetrics>; model_comparison: Array<Record<string, string | number | null>>;
  historical_winner: string; variability_summary: Record<string, unknown>;
  permutation_stability_status: "not_evaluated_single_row_folds";
  limitations: string[]; legacy_holdout: Record<string, unknown>;
}
export interface CandidateComparisonSummary {
  model_selection_status: "comparison_complete_and_adopted" | "not_run_current_pipeline";
  comparison_selected_model: string | null;
  comparison_selected_model_reason?: string;
  current_forecast_model: "random_forest";
  adoption_status: "adopted_p1.2b";
  adoption_policy_version?: "p1.2b-v1";
  message?: string;
  warning?: string;
  primary_metric?: "MAE";
  selection_policy?: Record<string, unknown>;
  candidates?: Array<{ model_id: string; model_family: string; parameters: Record<string, unknown>; preprocessing: Record<string, unknown> }>;
  aggregate_metrics?: Record<string, { successful_folds: number; failed_folds: number; mae: number; rmse: number; wape: number; median_absolute_error: number; negative_raw_prediction_count: number; clipping_count: number }>;
  wins_ties_losses?: Record<string, { better_fold_count: number; tied_fold_count: number; worse_fold_count: number }>;
  selection_eligibility?: Record<string, boolean>;
  model_failures?: Record<string, unknown[]>;
  limitations?: string[];
  uncertainty_source?: string;
  active_model_rolling_metrics?: Record<string, number>;
}

export interface DashboardSummaryOperationalSummary {
  total_recommendations: number;
  critical_priority_zones: number;
  facilities_with_expected_bed_gap: number;
  facilities_with_worst_case_bed_gap: number;
  critical_supply_alerts: number;
  highest_priority_zone: string;
  highest_pressure_facility: string;
}

export interface DashboardSummary {
  provenance: ArtifactProvenance;
  project: {
    title: string;
    subtitle: string;
    track: string;
    conference: string;
    mode: string;
    last_updated: string;
    data_status: string;
  };
  headline_metrics: DashboardSummaryHeadlineMetrics;
  uncertainty: DashboardSummaryUncertainty;
  preparedness_scenarios: DashboardPreparednessScenarios;
  model_evidence: DashboardSummaryModelEvidence;
  operational_summary: DashboardSummaryOperationalSummary;
  ethics_and_assumptions: string[];
  deployment_profile?: DeploymentProfileMetadata;
  feature_importance: FeatureDiagnostics;
  rolling_validation: RollingValidationSummary;
  candidate_model_comparison: CandidateComparisonSummary;
  workflow_metadata?: {
    runtime_connector_status: "pending_p1.4";
    current_approved_model_id: "random_forest";
    current_approved_model_label: "Random Forest";
    deployment_context: string;
    deployment_gate: DeploymentGate;
    forecast_horizon_days: number;
    dataset_reassessment_required: true;
    validation_status?: string;
    accepted_period?: {
      start: { epi_year: number; epi_week: number };
      end: { epi_year: number; epi_week: number };
    };
  };
  historical_gbr_evidence?: {
    status: string;
    model_explainability_artifact_path: string;
    model_explainability_artifact_sha256: string;
    rolling_validation_artifact_path: string;
    validation_metrics_artifact_path: string;
  };
}

// ─── Pipeline Run Summary ──────────────────────────────────────────────────

export interface PipelineRunSummary {
  provenance: ArtifactProvenance;
  run_timestamp: string;
  status: "success" | "partial" | "failed";
  completed_steps: string[];
  step_timings_sec: Record<string, number>;
  generated_files: string[];
  forecast_summary: {
    forecast_cases: number;
    growth_factor: number;
    risk_level: string;
    risk_score: number;
    target_epi_week: number;
    target_epi_year: number;
    best_case: number;
    expected_case: number;
    worst_case: number;
  };
  directives_summary: {
    total_facilities: number;
    total_public_government_anchors: number;
    critical_priority_zones: number;
    facilities_with_expected_bed_gap: number;
    facilities_with_worst_case_bed_gap: number;
    critical_supply_alerts: number;
    highest_priority_zone: string;
    highest_pressure_facility: string;
    total_recommendations: number;
  };
  deployment_profile?: DeploymentProfileMetadata;
}

// ─── UI helpers ────────────────────────────────────────────────────────────

export type ScenarioKey = "best_case" | "expected_case" | "worst_case";

export interface NavLink {
  href: string;
  label: string;
}
