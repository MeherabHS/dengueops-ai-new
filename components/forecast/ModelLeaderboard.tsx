import StatusBadge from "@/components/ui/StatusBadge";
import { modelLabel, statusLabel } from "@/lib/status-labels";
import type { ModelSuitabilityAssessment } from "@/lib/forecast-workflow-types";

const metric = (value: number | null | undefined, suffix = "") => value == null ? "—" : `${value.toFixed(2)}${suffix}`;

export default function ModelLeaderboard({ assessment }: { assessment: ModelSuitabilityAssessment }) {
  const candidates = assessment.workflow.candidates;
  const requiredFolds = assessment.foldPolicy.plannedFoldCount;
  return <div className="overflow-x-auto rounded-xl border border-border-subtle">
    <table className="w-full min-w-[1180px] text-left text-sm">
      <caption className="sr-only">Candidate ranking derived from this assessment. All returned candidates remain visible, including ineligible candidates.</caption>
      <thead className="bg-surface-muted text-xs uppercase tracking-wide text-ink-muted">
        <tr>{["Rank", "Candidate", "Eligibility", "Folds completed / required", "MAE", "RMSE", "WAPE", "Candidate type", "Governed evidence"].map((value) => <th key={value} className="px-4 py-3">{value}</th>)}</tr>
      </thead>
      <tbody className="divide-y divide-border-subtle">
        {candidates.map((candidate) => {
          const eligibleOverride = candidate.status === "eligible_non_winner"
            && candidate.candidateClass === "learned_model"
            && candidate.completionStatus === "complete"
            && candidate.failedFolds === 0
            && candidate.deployableForOneRun;
          return <tr key={candidate.modelId} className="bg-surface align-top" data-candidate-status={candidate.status}>
            <td className="px-4 py-3 font-semibold text-ink">{candidate.displayRank ?? "Not ranked"}</td>
            <td className="px-4 py-3">
              <p className="font-semibold text-ink">{candidate.modelLabel || modelLabel(candidate.modelId)}</p>
              <p className="mt-1 text-xs text-ink-muted">{candidate.modelFamily}</p>
              <div className="mt-2 flex flex-wrap gap-1">
                {candidate.technicalWinner ? <StatusBadge label="Technical winner" variant="success" /> : null}
                {eligibleOverride ? <StatusBadge label="Eligible override" variant="info" /> : null}
                {candidate.currentApprovedModel ? <StatusBadge label="Current assigned model" variant="neutral" /> : null}
                {!candidate.deployableForOneRun ? <StatusBadge label="Evaluation only" variant="warning" /> : null}
              </div>
            </td>
            <td className="px-4 py-3">
              <StatusBadge
                label={candidate.status === "ineligible" ? statusLabel(candidate.completionStatus === "incomplete" ? "candidate_incomplete" : "candidate_ineligible") : "Eligible"}
                variant={candidate.status === "ineligible" ? "warning" : "success"}
              />
            </td>
            <td className="px-4 py-3 text-ink-muted">{candidate.successfulFolds} / {requiredFolds}</td>
            <td className="px-4 py-3 text-ink">{metric(candidate.metrics?.mae)}</td>
            <td className="px-4 py-3 text-ink">{metric(candidate.metrics?.rmse)}</td>
            <td className="px-4 py-3 text-ink">{metric(candidate.metrics?.wape, "%")}</td>
            <td className="px-4 py-3 text-ink-muted">{candidate.candidateClass === "learned_model" ? "Learned model" : "Baseline"}</td>
            <td className="px-4 py-3">
              <p className="text-xs font-medium text-ink">{candidate.status === "technical_winner" ? "Technical winner for this dataset" : eligibleOverride ? "May be selected only by governed override" : "Not selectable"}</p>
              <ul className="mt-2 space-y-1 text-xs text-ink-muted">
                {candidate.reasons.length ? candidate.reasons.map((reason, index) => <li key={`${candidate.modelId}-${index}`}>• {reason}</li>) : <li>No rejection reason recorded.</li>}
              </ul>
            </td>
          </tr>;
        })}
      </tbody>
    </table>
    <p className="border-t border-border-subtle bg-surface-muted px-4 py-3 text-xs text-ink-muted">Candidate ranking derived from this assessment. Ineligible candidates remain visible but cannot be selected for a governed decision.</p>
  </div>;
}
