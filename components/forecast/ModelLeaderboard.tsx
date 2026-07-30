import StatusBadge from "@/components/ui/StatusBadge";
import { modelLabel, primaryCandidateStatusLabel, statusLabel } from "@/lib/status-labels";
import type { ModelSuitabilityAssessment } from "@/lib/forecast-workflow-types";
import type { AssessmentCandidateProjection } from "@/lib/runtime/contracts";

const metric = (value: number | null | undefined, suffix = "") =>
  value == null ? "Not available" : `${value.toFixed(2)}${suffix}`;

function candidateStatus(candidate: AssessmentCandidateProjection) {
  const baseline = candidate.candidateClass !== "learned_model";
  const eligibleOverride = candidate.status === "eligible_non_winner"
    && candidate.candidateClass === "learned_model"
    && candidate.completionStatus === "complete"
    && candidate.failedFolds === 0
    && candidate.deployableForOneRun;
  const primaryLabel = primaryCandidateStatusLabel(
    candidate.candidateClass,
    candidate.status,
    candidate.completionStatus,
  );
  return { baseline, eligibleOverride, primaryLabel };
}

function TechnicalEvidence({
  candidate,
  assessment,
}: {
  candidate: AssessmentCandidateProjection;
  assessment: ModelSuitabilityAssessment;
}) {
  const { eligibleOverride } = candidateStatus(candidate);
  return (
    <details className="group">
      <summary className="cursor-pointer rounded text-xs font-semibold text-accent outline-none focus-visible:ring-2 focus-visible:ring-focus">
        Technical evidence for {modelLabel(candidate.modelId)}
      </summary>
      <dl className="mt-3 grid gap-2 text-xs text-ink-muted">
        <div><dt className="font-medium text-ink">Candidate ID</dt><dd className="break-all font-mono">{candidate.modelId}</dd></div>
        <div><dt className="font-medium text-ink">Estimator family or class</dt><dd>{candidate.modelFamily}</dd></div>
        <div><dt className="font-medium text-ink">Candidate type</dt><dd>{candidate.candidateClass === "learned_model" ? "Learned model" : "Baseline"}</dd></div>
        <div><dt className="font-medium text-ink">Execution mode</dt><dd>{statusLabel(candidate.executionMode)}</dd></div>
        <div><dt className="font-medium text-ink">Current governed policy</dt><dd>{assessment.workflow.assessmentPolicy.policyId} · {assessment.workflow.assessmentPolicy.policyVersion}</dd></div>
        <div><dt className="font-medium text-ink">Decision evidence</dt><dd>{candidate.status === "technical_winner" ? "Technical winner for this dataset" : eligibleOverride ? "May be selected only by governed override" : "Not selectable"}</dd></div>
      </dl>
      <div className="mt-3 text-xs text-ink-muted">
        <p className="font-medium text-ink">Evidence explanation</p>
        <ul className="mt-1 space-y-1">
          {candidate.reasons.length
            ? candidate.reasons.map((reason, index) => <li key={`${candidate.modelId}-${index}`}>• {reason}</li>)
            : <li>No rejection or ineligibility reason recorded.</li>}
        </ul>
      </div>
    </details>
  );
}

function MetricGrid({ candidate }: { candidate: AssessmentCandidateProjection }) {
  return (
    <dl className="grid grid-cols-2 gap-3 text-sm">
      {[
        ["MAE", metric(candidate.metrics?.mae)],
        ["RMSE", metric(candidate.metrics?.rmse)],
        ["WAPE", metric(candidate.metrics?.wape, "%")],
        ["MSE", metric(candidate.metrics?.mse)],
        ["R²", metric(candidate.metrics?.r2)],
      ].map(([label, value]) => (
        <div key={label} className="rounded-lg bg-surface-muted p-3">
          <dt className="text-xs font-medium text-ink-muted">{label}</dt>
          <dd className="mt-1 font-mono tabular-nums text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export default function ModelLeaderboard({ assessment }: { assessment: ModelSuitabilityAssessment }) {
  const candidates = assessment.workflow.candidates;
  const requiredFolds = assessment.foldPolicy.plannedFoldCount;
  return (
    <div className="rounded-xl border border-border-subtle">
      <div className="hidden md:block">
        <table className="w-full table-fixed text-left text-xs lg:text-sm">
          <caption className="sr-only">Candidate ranking derived from this assessment. All returned candidates remain visible, including ineligible candidates.</caption>
          <colgroup>
            <col className="w-[5%]" />
            <col className="w-[18%]" />
            <col className="w-[10%]" />
            <col className="w-[11%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[8%]" />
            <col className="w-[16%]" />
          </colgroup>
          <thead className="bg-surface-muted text-[11px] uppercase tracking-wide text-ink-muted">
            <tr>
              {["Rank", "Model", "Status", "Folds", "MAE", "RMSE", "WAPE", "MSE", "R²", "Details"].map((value) => (
                <th key={value} scope="col" className="px-2 py-3 align-bottom">{value}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border-subtle">
            {candidates.map((candidate) => {
              const { baseline, eligibleOverride, primaryLabel } = candidateStatus(candidate);
              return (
                <tr key={candidate.modelId} className="bg-surface align-top" data-candidate-status={candidate.status}>
                  <td className="px-2 py-3 font-semibold text-ink">{candidate.displayRank ?? "—"}</td>
                  <th scope="row" className="px-2 py-3 font-semibold leading-snug text-ink">{modelLabel(candidate.modelId)}</th>
                  <td className="px-2 py-3">
                    <div className="flex flex-col items-start gap-1">
                      <StatusBadge label={primaryLabel} variant={candidate.status === "ineligible" || baseline ? "warning" : "success"} />
                      {baseline ? <span className="text-[11px] text-ink-muted">Evaluation only</span> : null}
                      {candidate.technicalWinner ? <StatusBadge label="Technical winner" variant="success" /> : null}
                      {eligibleOverride ? <StatusBadge label="Eligible override" variant="info" /> : null}
                    </div>
                  </td>
                  <td className="px-2 py-3 text-ink-muted"><span className="block tabular-nums">{candidate.successfulFolds} / {requiredFolds}</span><span className="mt-1 block text-[11px]">{candidate.failedFolds} failed</span></td>
                  <td className="px-2 py-3 font-mono tabular-nums text-ink">{metric(candidate.metrics?.mae)}</td>
                  <td className="px-2 py-3 font-mono tabular-nums text-ink">{metric(candidate.metrics?.rmse)}</td>
                  <td className="px-2 py-3 font-mono tabular-nums text-ink">{metric(candidate.metrics?.wape, "%")}</td>
                  <td className="px-2 py-3 font-mono tabular-nums text-ink">{metric(candidate.metrics?.mse)}</td>
                  <td className="px-2 py-3 font-mono tabular-nums text-ink">{metric(candidate.metrics?.r2)}</td>
                  <td className="px-2 py-3"><TechnicalEvidence candidate={candidate} assessment={assessment} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ol className="divide-y divide-border-subtle md:hidden" aria-label="Candidate ranking">
        {candidates.map((candidate) => {
          const { baseline, eligibleOverride, primaryLabel } = candidateStatus(candidate);
          return (
            <li key={candidate.modelId} className="space-y-4 bg-surface p-4" data-candidate-status={candidate.status}>
              <div className="flex items-start justify-between gap-3">
                <div><p className="text-xs text-ink-muted">Rank {candidate.displayRank ?? "not assigned"}</p><h3 className="mt-1 font-semibold text-ink">{modelLabel(candidate.modelId)}</h3></div>
                <div className="flex flex-col items-end gap-1">
                  <StatusBadge label={baseline ? primaryLabel : candidate.status === "ineligible" ? "Ineligible" : candidate.technicalWinner ? "Technical winner" : eligibleOverride ? "Eligible override" : primaryLabel} variant={candidate.status === "ineligible" || baseline ? "warning" : candidate.technicalWinner ? "success" : "info"} />
                  {baseline ? <span className="text-xs text-ink-muted">Evaluation only</span> : null}
                </div>
              </div>
              <p className="text-sm text-ink-muted"><span className="font-medium text-ink">Folds:</span> {candidate.successfulFolds} / {requiredFolds} completed · {candidate.failedFolds} failed</p>
              <MetricGrid candidate={candidate} />
              <TechnicalEvidence candidate={candidate} assessment={assessment} />
            </li>
          );
        })}
      </ol>
      <p className="border-t border-border-subtle bg-surface-muted px-4 py-3 text-xs text-ink-muted">Candidate ranking is preserved from verified assessment evidence. MSE and R² are secondary diagnostics and do not change the technical winner.</p>
    </div>
  );
}
