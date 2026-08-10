export type AvailabilityScenario =
  | "baseline_availability"
  | "constrained_availability"
  | "severe_constraint";

export type PublicReadinessStatus =
  | "warning"
  | "no_calculated_gap"
  | "insufficient_data"
  | "not_calculated";

export interface PublicSeriesPoint {
  period: string;
  date: null;
  cases: number;
}

export interface PublicForecast {
  forecastedCases: number;
  forecastPeriod: {
    targetPeriod: string;
    horizonWeeks: number;
    interpretation: "two_week_ahead_target_period";
  };
  recentObservedSeries: PublicSeriesPoint[];
  forecastSeries: PublicSeriesPoint[];
  latestObservedPoint: PublicSeriesPoint;
  forecastPoint: PublicSeriesPoint;
  forecast_growth_category: "increasing" | "decreasing" | "stable";
  directionLabel: "Expected rise" | "Expected decrease" | "Expected to remain stable";
  directionIndicator: "up" | "down" | "stable";
  growthPercentage: null;
  growthComparisonStatus: "equivalent_period_unavailable";
  uncertainty: {
    presentationMode: "point_only"|"point_and_interval";
    intervalAvailable: boolean;
    lower: number|null;
    upper: number|null;
    publicLabel: "Prediction interval unavailable"|"Calibrated prediction interval";
    reason: string;
  };
}

export interface PublicHospital {
  id: string;
  name: string;
  location: string | null;
  active: true;
  participationStatus: "included";
  managementDecisionStatus: "pending_review";
  capacityReference: number | null;
  capacityReferenceStatus: "available" | "unavailable";
  currentAvailableBeds: null;
  currentAvailabilityStatus: "unknown";
  syntheticAvailableBedUnits: number | null;
  readinessStatus: PublicReadinessStatus;
  calculatedGap: number | null;
  ns1RdtStatus: "unknown";
  ivFluidStatus: "unknown";
  lastUpdatedAt: string;
  evidenceClassification: "synthetic_qualification"|"current_operational_preparedness";
  operationalUseAllowed: boolean;
}

export interface PublicPreparedness {
  selectedScenario: AvailabilityScenario|null;
  availableScenarios: Array<{ id: AvailabilityScenario; label: string }>;
  scenarioExplanation: string;
  participatingHospitals: number;
  capacityKnownHospitals: number;
  capacityUnknownHospitals: number;
  calculatedGapHospitals: number;
  noCalculatedGapHospitals: number;
  insufficientDataHospitals: number;
  hospitals: PublicHospital[];
  evidenceClassification:"synthetic_qualification"|"current_operational_preparedness";
}

export interface PublicEvidenceClassification {
  classification: "synthetic_qualification"|"current_operational_preparedness";
  operationalDhakaValidation: boolean;
  operationalPreparednessEvidencePublished: boolean;
  productionFormulaActivated: boolean;
  operationalUseAllowed: boolean;
}

export interface PublicForecastResponse {
  schemaVersion: "1.0";
  area: { id: "dhaka_south"; displayName: "Dhaka" };
  forecast: PublicForecast;
  freshness: { updatedAt: string; state: "current" };
  evidence: Pick<
    PublicEvidenceClassification,
    "classification" | "operationalDhakaValidation" | "operationalUseAllowed"
  >;
}

export interface PublicDashboardResponse {
  schemaVersion: "1.0";
  area: { id: "dhaka_south"; displayName: "Dhaka" };
  forecast: PublicForecast;
  preparedness: PublicPreparedness;
  qualificationPreparedness: PublicPreparedness|null;
  freshness: { updatedAt: string; state: "current" };
  evidence: PublicEvidenceClassification;
}

export type PublicHospitalsResponse = PublicDashboardResponse;

export interface CommunityCurrentV1 {
  schemaVersion: "1.0";
  deployment: { id: "dhaka_south"; displayName: "Dhaka" };
  generatedAt: string;
  forecast: {
    status: "available" | "unavailable";
    targetPeriod: string | null;
    pointCases: number | null;
    trend: {
      direction: "up" | "down" | "stable" | "unknown";
      changeCases: number | null;
    };
    series: {
      observed: Array<{ period: string; cases: number }>;
      forecast: Array<{ period: string; cases: number; lower: number | null; upper: number | null }>;
    };
    uncertainty: { status: "available" | "point_only"; nominalLevel: number | null };
    confidence: { status: "available" | "unavailable" | "pending"; score: number | null; band: "high" | "moderate" | "low" | null };
  };
  preparedness: {
    status: "available" | "pending" | "unavailable";
    facilities: Array<{
      facilityName: string;
      participation: "included";
      officialCapacityReference: number | null;
      liveAvailability: null;
      formulaDerivedPreparedness: { value: number | null; unit: string };
      planningState: "calculated" | "insufficient_data";
    }>;
  };
}

export type VectorGovernanceReason =
  | "test_submission"
  | "duplicate"
  | "unusable_image"
  | "invalid_location"
  | "irrelevant_content"
  | "user_request"
  | "other";

export interface VectorAnalysisDispositionV1 {
  status: "included" | "excluded";
  reason: VectorGovernanceReason | null;
  note: string | null;
  changedAt: string | null;
  changedBy: string | null;
}

export interface VectorSubmissionMetadataV1 {
  schemaVersion: "1.0";
  submissionId: string;
  clientSubmissionId: string | null;
  receivedAt: string;
  capturedAt: string | null;
  contentType: "image/jpeg" | "image/png" | "image/webp";
  byteSize: number;
  sha256: string;
  storageKey: string;
  latitude: number | null;
  longitude: number | null;
  locationAccuracyM: number | null;
  note: string | null;
  status: "received";
  analysisDisposition: VectorAnalysisDispositionV1;
}

export interface VectorAnalyticalSubmissionV1 {
  submissionId: string;
  clientSubmissionId: string | null;
  latitude: number;
  longitude: number;
  accuracyMeters: number | null;
  capturedAt: string | null;
  receivedAt: string;
  classificationStatus: "unreviewed";
  processingState: "received";
  logicalObservationStatus: "client_id_bound" | "legacy_unverified";
  analysisDisposition: "included";
}

export interface VectorDeletionTombstoneV1 {
  schemaVersion: "1.0";
  submissionId: string;
  clientSubmissionId: string | null;
  deletedAt: string;
  deletedBy: string;
  deletionReason: VectorGovernanceReason;
  originalEvidenceSha256: string;
}

export interface VectorSubmissionReceiptV1 {
  schemaVersion: "1.0";
  submissionId: string;
  status: "received";
  receivedAt: string;
}
