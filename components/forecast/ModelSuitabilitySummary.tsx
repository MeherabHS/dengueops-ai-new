import EmptyState from "@/components/ui/EmptyState";
import { modelLabel, statusLabel } from "@/lib/status-labels";
import type { ModelSuitabilityAssessment } from "@/lib/forecast-workflow-types";
import ModelLeaderboard from "./ModelLeaderboard";
import RecommendationStrengthBadge from "./RecommendationStrengthBadge";

export default function ModelSuitabilitySummary({ assessment }: { assessment: ModelSuitabilityAssessment | null }) {
  if (!assessment) return <EmptyState title="Assessment not completed" description="Start the governed temporal assessment to produce technical comparison evidence. No winner or forecast has been generated." />;
  const workflow = assessment.workflow;
  const compatibility = String(workflow.decisionCompatibilityStatus);
  const decisionAvailable = compatibility === "phase1_decision_policy_available" || compatibility === "phase2_decision_policy_available";
  return <section className="space-y-5" aria-labelledby="assessment-result-title">
    <div className="rounded-xl border border-border-subtle bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><p className="text-xs uppercase tracking-wide text-ink-muted">Technical winner for this dataset</p><h2 id="assessment-result-title" className="mt-1 text-xl font-semibold text-ink">{assessment.technicalWinnerModelId ? modelLabel(assessment.technicalWinnerModelId) : "No technical winner"}</h2></div>
        <RecommendationStrengthBadge strength={assessment.recommendationStrength} />
      </div>
      <p className="mt-3 text-sm text-ink-muted">{assessment.selectionReason}</p>
      <p className="mt-2 text-xs text-warning">The winner was derived from the uploaded dataset&apos;s verified assessment performance. {decisionAvailable ? "The current governed policy permits a separate Super User decision and one-run authorization; automatic adoption remains disabled." : "No governed decision policy matches this committed identity, so decision controls fail closed."}</p>
      {!workflow.technicalWinnerDeployable && assessment.technicalWinnerModelId && decisionAvailable ? <p className="mt-2 text-xs font-medium text-warning">This technical winner is an evaluation-only baseline and cannot authorize a forecast. No learned candidate is substituted automatically.</p> : null}
    </div>
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Summary label="Assessment" value={`${assessment.assessmentId.slice(0, 12)}…`} detail={`${workflow.assessmentPolicy.policyId} · ${workflow.assessmentPolicy.policyVersion}`} />
      <Summary label="Dataset" value={`${assessment.datasetId.slice(0, 12)}…`} detail={`${assessment.acceptedPeriod.start} to ${assessment.acceptedPeriod.end} · ${assessment.labelledRows} labelled rows`} />
      <Summary label="Fold design" value={`${assessment.foldPolicy.plannedFoldCount} common folds`} detail={`${assessment.foldPolicy.initialTrainingRows} initial rows · ${assessment.foldPolicy.embargoRows}-row embargo · ${assessment.foldPolicy.horizonWeeks}-week horizon`} />
      <Summary label="Current assigned model" value={modelLabel(workflow.currentApprovedModelId)} detail={`${workflow.currentApprovedModelFamily} · assignment authority unchanged`} />
    </div>
    <div className="grid gap-4 md:grid-cols-3">
      <Summary label="Candidate set" value={statusLabel(assessment.candidateSetStatus)} detail={`${workflow.candidates.length} candidates returned by verified assessment`} />
      <Summary label="Winner deployability" value={workflow.technicalWinnerDeployable ? "Eligible for one-run decision" : "Evaluation only"} detail="Baseline candidates cannot authorize forecasting" />
      <Summary label={decisionAvailable ? "Current governed policy" : "Decision policy unavailable"} value={workflow.decision ? statusLabel(workflow.decision.decisionStatus) : "Decision not recorded"} detail={workflow.decision?.selectedModelId ? `${modelLabel(workflow.decision.selectedModelId)} · ${statusLabel(workflow.decision.authorizationStatus)}` : "No governed selected candidate"} />
    </div>
    <ModelLeaderboard assessment={assessment} />
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-xl border border-border-subtle bg-surface p-5"><h3 className="font-semibold text-ink">Comparison safeguards</h3><dl className="mt-3 space-y-2 text-sm text-ink-muted"><div><dt className="inline font-medium text-ink">Same folds for every candidate: </dt><dd className="inline">Yes</dd></div><div><dt className="inline font-medium text-ink">Naive baseline requirement: </dt><dd className="inline">{assessment.baselineRequirementSatisfied ? "Satisfied" : "Not satisfied"}</dd></div><div><dt className="inline font-medium text-ink">Learned-model requirement: </dt><dd className="inline">{assessment.learnedModelRequirementSatisfied ? "Satisfied" : "Not satisfied"}</dd></div><div><dt className="inline font-medium text-ink">Recommendation: </dt><dd className="inline">{statusLabel(assessment.recommendationStatus)}</dd></div><div><dt className="inline font-medium text-ink">Adoption: </dt><dd className="inline">{statusLabel(assessment.adoptionStatus)}</dd></div></dl></div>
      <div className="rounded-xl border border-warning/25 bg-warning/10 p-5"><h3 className="font-semibold text-ink">Limitations</h3><ul className="mt-3 space-y-2 text-sm text-ink-muted">{assessment.limitations.map((value) => <li key={value}>• {value}</li>)}</ul></div>
    </div>
  </section>;
}

function Summary({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-border-subtle bg-surface p-4"><p className="text-xs uppercase tracking-wide text-ink-muted">{label}</p><p className="mt-2 font-semibold text-ink">{value}</p><p className="mt-1 text-xs text-ink-muted">{detail}</p></div>;
}
