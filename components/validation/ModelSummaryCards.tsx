import { candidateModelComparison as comparison } from "@/lib/demo-data";
import { modelLabel, statusLabel } from "@/lib/status-labels";

export default function ModelSummaryCards() {
  return <section id="model-cards" className="mb-10"><p className="text-xs font-semibold uppercase tracking-wider text-accent">Selection status</p><h2 className="mt-1 text-2xl font-bold text-primary">Comparison and active model</h2><div className="mt-5 grid gap-4 sm:grid-cols-3">{[["Comparison status",statusLabel(comparison.model_selection_status)],["Comparison winner",modelLabel(comparison.comparison_selected_model)],["Active forecast model",modelLabel(comparison.current_forecast_model)]].map(([label,value]) => <div key={label} className="rounded-xl border border-border bg-surface p-5"><p className="text-[10px] uppercase tracking-wider text-text-muted">{label}</p><p className="mt-2 text-sm font-bold text-primary">{value}</p></div>)}</div><p className="mt-4 text-xs text-secondary">{statusLabel(comparison.adoption_status)}. Random Forest is active for this synthetic benchmark deployment only.</p></section>;
}
