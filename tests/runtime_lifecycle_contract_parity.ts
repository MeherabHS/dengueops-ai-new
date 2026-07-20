import type {
  BootstrapLifecycleDecision,
  BootstrapLifecycleJob,
  BootstrapModelAssignment,
  CommittedAssignmentActiveModelAuthority,
  CommittedAssignmentQuickForecastJob,
  DeferLifecycleDecision,
  DeferLifecycleJob,
  HistoricalProfileFallbackQuickForecastJob,
  HistoricalProfileActiveModelAuthority,
  HistoricalQuickForecastJob,
  LifecycleDecisionCommit,
  ModelAssignment,
  ModelAssignmentCommit,
  ModelAssignmentLatest,
  ModelLifecycleJobRecord,
  PromotionLifecycleDecision,
  PromotionLifecycleJob,
  PromotionModelAssignment,
  RejectLifecycleDecision,
  RejectLifecycleJob,
  RetentionLifecycleDecision,
  RetentionLifecycleJob,
  RollbackLifecycleDecision,
  RollbackLifecycleJob,
  RollbackModelAssignment,
} from "../lib/runtime/contracts";

type Expect<T extends true> = T;
type Equal<Left, Right> = (<Value>() => Value extends Left ? 1 : 2) extends
  (<Value>() => Value extends Right ? 1 : 2) ? true : false;

type _JobUsesExpectedAssessment = Expect<Equal<"expectedAssessmentCommitSha256" extends keyof PromotionLifecycleJob ? true : false, true>>;
type _JobRejectsCommittedAssessment = Expect<Equal<"assessmentCommitSha256" extends keyof PromotionLifecycleJob ? true : false, false>>;
type _DecisionUsesCommittedAssessment = Expect<Equal<"assessmentCommitSha256" extends keyof PromotionLifecycleDecision ? true : false, true>>;
type _DecisionRejectsExpectedAssessment = Expect<Equal<"expectedAssessmentCommitSha256" extends keyof PromotionLifecycleDecision ? true : false, false>>;
type _BootstrapDecisionUsesCommittedProfile = Expect<Equal<"profileSha256" extends keyof BootstrapLifecycleDecision ? true : false, true>>;
type _BootstrapDecisionRejectsExpectedProfile = Expect<Equal<"expectedProfileSha256" extends keyof BootstrapLifecycleDecision ? true : false, false>>;
type _JobsAreDiscriminated = Expect<Equal<ModelLifecycleJobRecord["action"], "bootstrap_historical_profile"|"retain_current_model"|"promote_selected_model"|"rollback_previous_assignment"|"defer"|"reject">>;
type _DecisionCommitsAreDiscriminated = Expect<Equal<LifecycleDecisionCommit["action"], ModelLifecycleJobRecord["action"]>>;
type _AssignmentsAreDiscriminated = Expect<Equal<ModelAssignment["assignmentAction"], "bootstrap"|"promote"|"rollback">>;
type _AssignmentCommitsAreDiscriminated = Expect<Equal<ModelAssignmentCommit["assignmentAction"], ModelAssignment["assignmentAction"]>>;
type _LatestIsDiscriminated = Expect<Equal<ModelAssignmentLatest["assignmentAction"], ModelAssignment["assignmentAction"]>>;
type _HistoricalQuickHasNoAuthorityRequirement = HistoricalQuickForecastJob;
type _FallbackQuickHasProfileAuthority = Expect<Equal<HistoricalProfileFallbackQuickForecastJob["activeModelAuthoritySource"], "historical_profile_fallback_pending_explicit_bootstrap">>;
type _CommittedQuickHasAssignmentAuthority = Expect<Equal<CommittedAssignmentQuickForecastJob["activeModelAuthoritySource"], "committed_assignment">>;
type _EveryLifecycleJob = BootstrapLifecycleJob|PromotionLifecycleJob|RetentionLifecycleJob|RollbackLifecycleJob|DeferLifecycleJob|RejectLifecycleJob;
type _EveryLifecycleDecision = BootstrapLifecycleDecision|PromotionLifecycleDecision|RetentionLifecycleDecision|RollbackLifecycleDecision|DeferLifecycleDecision|RejectLifecycleDecision;
type _EveryAssignment = BootstrapModelAssignment|PromotionModelAssignment|RollbackModelAssignment;
type _JobParity = Expect<Equal<_EveryLifecycleJob,ModelLifecycleJobRecord>>;
type _DecisionParity = Expect<Equal<_EveryLifecycleDecision,import("../lib/runtime/contracts").LifecycleDecision>>;
type _AssignmentParity = Expect<Equal<_EveryAssignment,ModelAssignment>>;
type _FallbackAuthorityHasProfile = Expect<Equal<HistoricalProfileActiveModelAuthority["profileSha256"],string>>;
type _CommittedAuthorityHasPointer = Expect<Equal<CommittedAssignmentActiveModelAuthority["assignmentPointerSha256"],string>>;
type _CommittedArtifactsRejectExpectedNames = Expect<Equal<"expectedAuthorizationCommitSha256" extends keyof LifecycleDecisionCommit ? true:false,false>>;
type _RequestRejectsCommittedNames = Expect<Equal<"authorizationCommitSha256" extends keyof PromotionLifecycleJob ? true:false,false>>;

export {};
