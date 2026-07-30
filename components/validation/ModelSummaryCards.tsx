import { historicalBenchmarkEvidence } from "@/lib/demo-data";
import { modelLabel, statusLabel } from "@/lib/status-labels";

export default function ModelSummaryCards() {
  const comparison = historicalBenchmarkEvidence.comparison;
  return <section id="model-cards" className="mb-10"><p className="text-xs font-semibold uppercase tracking-wider text-accent">Historical comparison</p><h2 className="mt-1 text-2xl font-bold text-primary">Historical benchmark model comparison</h2><div className="mt-5 grid gap-4 sm:grid-cols-3">{[["Comparison status",statusLabel(comparison.status)],["Historical benchmark winner",modelLabel(comparison.winnerModelId)],["Evidence classification","Benchmark evidence only"]].map(([label,value]) => <div key={label} className="rounded-xl border border-border bg-surface p-5"><p className="text-[10px] uppercase tracking-wider text-text-muted">{label}</p><p className="mt-2 text-sm font-bold text-primary">{value}</p></div>)}</div><p className="mt-4 text-xs text-secondary">These results describe an earlier deterministic synthetic benchmark and do not establish runtime assignment authority.</p></section>;
}
