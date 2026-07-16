import StatusBadge from "@/components/ui/StatusBadge";
import { modelLabel, statusLabel } from "@/lib/status-labels";
import type { ModelSuitabilityAssessment } from "@/lib/forecast-workflow-types";

const metric = (value: number | null | undefined, suffix = "") =>
  value == null ? "—" : `${value.toFixed(2)}${suffix}`;

export default function ModelLeaderboard({ assessment }: { assessment: ModelSuitabilityAssessment }) {
  const candidates = assessment.workflow.candidates;
  return <div className="overflow-x-auto rounded-xl border border-border-subtle"><table className="min-w-[1280px] w-full text-left text-sm">
    <caption className="sr-only">Derived candidate display order from committed governed comparison evidence. Ineligible candidates are not ranked.</caption>
    <thead className="bg-surface-muted text-xs uppercase tracking-wide text-ink-muted"><tr>{["Rank","Candidate","Evidence status","Folds","MAE","RMSE","WAPE","Median error","Maximum error","Clipping / warnings","Reasons"].map(value => <th key={value} className="px-4 py-3">{value}</th>)}</tr></thead>
    <tbody className="divide-y divide-border-subtle">{candidates.map(candidate => <tr key={candidate.modelId} className="bg-surface align-top">
      <td className="px-4 py-3 font-semibold text-ink">{candidate.displayRank ?? "Not ranked"}</td>
      <td className="px-4 py-3"><p className="font-semibold text-ink">{modelLabel(candidate.modelId)}</p><p className="mt-1 text-xs text-ink-muted">{candidate.modelFamily}</p><div className="mt-2 flex flex-wrap gap-1">{candidate.technicalWinner ? <StatusBadge label="Technical winner" variant="success" /> : null}{candidate.currentApprovedModel ? <StatusBadge label="Current deployment model" variant="info" /> : null}<StatusBadge label={candidate.deployableForOneRun ? "One-run deployable" : "Evaluation only"} variant={candidate.deployableForOneRun ? "info" : "warning"} /></div></td>
      <td className="px-4 py-3 text-ink-muted">{candidate.selectionEligible ? "Eligible" : statusLabel(candidate.completionStatus === "ineligible" ? "candidate_ineligible" : candidate.completionStatus === "incomplete" ? "candidate_incomplete" : "complete")}</td>
      <td className="px-4 py-3 text-ink-muted">{candidate.successfulFolds} / {candidate.failedFolds}</td>
      <td className="px-4 py-3 text-ink">{metric(candidate.metrics?.mae)}</td><td className="px-4 py-3 text-ink">{metric(candidate.metrics?.rmse)}</td><td className="px-4 py-3 text-ink">{metric(candidate.metrics?.wape, "%")}</td>
      <td className="px-4 py-3 text-ink">{metric(candidate.metrics?.medianAbsoluteError)}</td><td className="px-4 py-3 text-ink">{metric(candidate.metrics?.maximumAbsoluteError)}</td>
      <td className="px-4 py-3 text-ink-muted">{candidate.metrics ? `${candidate.metrics.clippingCount} / ${candidate.metrics.warningCount}` : "—"}</td>
      <td className="px-4 py-3"><ul className="space-y-1 text-xs text-ink-muted">{candidate.reasons.map((reason, index) => <li key={`${candidate.modelId}-${index}`}>• {reason}</li>)}</ul></td>
    </tr>)}</tbody>
  </table><p className="border-t border-border-subtle bg-surface-muted px-4 py-3 text-xs text-ink-muted">Rank is a derived display order from the committed eligibility-first MAE, RMSE, WAPE, median-error, maximum-error, complexity, and model-ID sequence. It is not a new persisted assessment artifact.</p></div>;
}
