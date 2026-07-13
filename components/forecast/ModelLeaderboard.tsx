import { modelLabel, statusLabel } from "@/lib/status-labels";
import type { ModelSuitabilityAssessment } from "@/lib/forecast-workflow-types";

const metric = (value: number | null | undefined, suffix = "") => value == null ? "—" : `${value.toFixed(2)}${suffix}`;

export default function ModelLeaderboard({ assessment }: { assessment: ModelSuitabilityAssessment }) {
  const ranked = new Map(assessment.candidates.filter(candidate => candidate.selectionEligible).sort((a, b) => (a.metrics?.mae ?? Infinity) - (b.metrics?.mae ?? Infinity)).map((candidate, index) => [candidate.modelId, index + 1]));
  return <div className="overflow-x-auto rounded-xl border border-border-subtle"><table className="min-w-[1000px] w-full text-left text-sm">
    <caption className="sr-only">Dataset-specific candidate leaderboard. Ineligible and incomplete candidates are not ranked.</caption>
    <thead className="bg-surface-muted text-xs uppercase tracking-wide text-ink-muted"><tr>{["Rank","Candidate","Status","Folds","MAE","RMSE","WAPE","Median error","Maximum error","Clipping / warnings"].map(value => <th key={value} className="px-4 py-3">{value}</th>)}</tr></thead>
    <tbody className="divide-y divide-border-subtle">{assessment.candidates.map(candidate => <tr key={candidate.modelId} className="bg-surface align-top">
      <td className="px-4 py-3 font-semibold text-ink">{ranked.get(candidate.modelId) ?? "Not ranked"}</td>
      <td className="px-4 py-3"><p className="font-semibold text-ink">{modelLabel(candidate.modelId)}</p><p className="mt-1 text-xs text-ink-muted">{candidate.reasons[0]}</p></td>
      <td className="px-4 py-3 text-ink-muted">{statusLabel(candidate.completionStatus === "ineligible" ? "candidate_ineligible" : candidate.completionStatus === "incomplete" ? "candidate_incomplete" : "complete")}</td>
      <td className="px-4 py-3 text-ink-muted">{candidate.successfulFolds} / {candidate.failedFolds}</td>
      <td className="px-4 py-3 text-ink">{metric(candidate.metrics?.mae)}</td><td className="px-4 py-3 text-ink">{metric(candidate.metrics?.rmse)}</td><td className="px-4 py-3 text-ink">{metric(candidate.metrics?.wape, "%")}</td>
      <td className="px-4 py-3 text-ink">{metric(candidate.metrics?.medianAbsoluteError)}</td><td className="px-4 py-3 text-ink">{metric(candidate.metrics?.maximumAbsoluteError)}</td>
      <td className="px-4 py-3 text-ink-muted">{candidate.metrics ? `${candidate.metrics.clippingCount} / ${candidate.metrics.warningCount}` : "—"}</td>
    </tr>)}</tbody>
  </table></div>;
}
