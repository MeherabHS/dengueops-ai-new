import type { AssessmentCandidateSummary, RuntimeCandidateId } from "./contracts";

const TOLERANCE = 1e-9;
const METRICS = [
  "mae",
  "rmse",
  "wape",
  "medianAbsoluteError",
  "maximumAbsoluteError",
] as const;

function choose(candidates: AssessmentCandidateSummary[]): AssessmentCandidateSummary {
  let remaining = [...candidates];
  for (const key of METRICS) {
    const values = remaining.map((candidate) => candidate.metrics?.[key]);
    if (values.some((value) => value == null || !Number.isFinite(value))) {
      throw new Error(`Unavailable governed display-order metric: ${key}.`);
    }
    const best = Math.min(...(values as number[]));
    remaining = remaining.filter(
      (candidate) => Math.abs(Number(candidate.metrics?.[key]) - best) <= TOLERANCE,
    );
    if (remaining.length === 1) return remaining[0];
  }
  const complexity = Math.min(...remaining.map((candidate) => candidate.selectionComplexityRank));
  remaining = remaining.filter((candidate) => candidate.selectionComplexityRank === complexity);
  return remaining.sort((left, right) => left.modelId.localeCompare(right.modelId))[0];
}

export function deriveAssessmentDisplayOrder(
  candidates: AssessmentCandidateSummary[],
): RuntimeCandidateId[] {
  const remaining = candidates.filter((candidate) => candidate.selectionEligible);
  const ordered: RuntimeCandidateId[] = [];
  while (remaining.length) {
    const winner = choose(remaining);
    ordered.push(winner.modelId);
    remaining.splice(remaining.indexOf(winner), 1);
  }
  return ordered.concat(
    candidates
      .filter((candidate) => !candidate.selectionEligible)
      .sort(
        (left, right) =>
          left.selectionComplexityRank - right.selectionComplexityRank ||
          left.modelId.localeCompare(right.modelId),
      )
      .map((candidate) => candidate.modelId),
  );
}
