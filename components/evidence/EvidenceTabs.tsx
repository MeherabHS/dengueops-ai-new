import Tabs from "@/components/ui/Tabs";
import StatusBadge from "@/components/ui/StatusBadge";
import ValidationDesignSection from "@/components/validation/ValidationDesignSection";
import ModelSummaryCards from "@/components/validation/ModelSummaryCards";
import ModelComparisonTable from "@/components/validation/ModelComparisonTable";
import ActualVsPredictedPanel from "@/components/validation/ActualVsPredictedPanel";
import ErrorComparisonPanel from "@/components/validation/ErrorComparisonPanel";
import UncertaintyLinkageSection from "@/components/validation/UncertaintyLinkageSection";
import ValidationLimitations from "@/components/validation/ValidationLimitations";
import FeatureImportanceChart from "@/components/charts/FeatureImportanceChart";
import { dashboardSummary, evidenceViewModel, featureDiagnostics, pipelineRunSummary } from "@/lib/demo-data";
import { modelLabel, statusLabel } from "@/lib/status-labels";

function DatasetValidation() {
  return <div><div className="mb-5 rounded-xl border border-informational/25 bg-informational/10 p-4"><h2 className="font-semibold text-primary">Current committed benchmark run</h2><p className="mt-1 text-sm text-secondary">This evidence describes the current deterministic synthetic benchmark. It does not validate a future uploaded dataset; governed runtime validation remains pending P1.4.</p></div><ValidationDesignSection /></div>;
}

function ModelSuitability() {
  return <div><p className="mb-5 max-w-4xl text-sm text-secondary">This recommendation applies to the current synthetic benchmark dataset and does not establish suitability for every future upload.</p><ModelSummaryCards/><ModelComparisonTable/></div>;
}

function ForecastEvaluation() {
  const active = dashboardSummary.candidate_model_comparison.active_model_rolling_metrics;
  return <div><UncertaintyLinkageSection/><section className="mb-10"><p className="text-xs font-semibold uppercase tracking-wider text-accent">Active-model evidence</p><h2 className="mt-1 text-xl font-bold text-primary">Active Random Forest rolling performance</h2>{active && <dl className="mt-4 grid gap-3 sm:grid-cols-3"><div className="rounded-xl border border-border bg-surface p-4"><dt className="text-xs text-text-muted">MAE</dt><dd className="mt-1 text-xl font-bold text-primary">{Number(active.mae).toFixed(2)}</dd></div><div className="rounded-xl border border-border bg-surface p-4"><dt className="text-xs text-text-muted">RMSE</dt><dd className="mt-1 text-xl font-bold text-primary">{Number(active.rmse).toFixed(2)}</dd></div><div className="rounded-xl border border-border bg-surface p-4"><dt className="text-xs text-text-muted">WAPE</dt><dd className="mt-1 text-xl font-bold text-primary">{Number(active.wape).toFixed(2)}</dd></div></dl>}</section><section className="rounded-2xl border border-border bg-surface-raised p-5"><p className="text-xs font-semibold uppercase tracking-wider text-warning">Historical compatibility evidence</p><h2 className="mt-1 text-lg font-bold text-primary">Historical P1.1 Gradient Boosting rolling-validation evidence — not active-model performance</h2><div className="mt-6"><ActualVsPredictedPanel/><ErrorComparisonPanel/></div></section></div>;
}

function Explainability() {
  return <div><div className="mb-5 flex flex-wrap gap-2"><StatusBadge label="Active Random Forest diagnostics" variant="info"/><StatusBadge label="Model diagnostic · not causal" variant="warning"/></div>{featureDiagnostics.status === "generated" ? <><div className="rounded-xl border border-border bg-surface p-4"><FeatureImportanceChart data={featureDiagnostics.feature_ranking}/></div><p className="mt-3 text-sm text-secondary">{featureDiagnostics.non_causal_warning} {featureDiagnostics.split_warning}</p></> : <p className="text-secondary">{featureDiagnostics.message}</p>}<div className="mt-5 rounded-xl border border-border bg-surface-raised p-4"><h3 className="font-semibold text-primary">Historical Gradient Boosting evidence</h3><p className="mt-1 text-sm text-secondary">Historical · Compatibility-only · Not active-model evidence.</p><details className="mt-3 text-xs text-text-muted"><summary className="cursor-pointer text-secondary">Technical artifact reference</summary><p className="mt-2 font-mono">{dashboardSummary.historical_gbr_evidence?.model_explainability_artifact_path ?? "data/model_explainability.json"}</p></details></div></div>;
}

function Provenance() {
  const provenance = evidenceViewModel.provenance;
  return <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-3"><div className="rounded-xl border border-border bg-surface p-4"><p className="text-xs text-text-muted">Run status</p><p className="mt-1 font-semibold text-primary">{statusLabel(pipelineRunSummary.status)}</p></div><div className="rounded-xl border border-border bg-surface p-4"><p className="text-xs text-text-muted">Active model</p><p className="mt-1 font-semibold text-primary">{modelLabel(dashboardSummary.candidate_model_comparison.current_forecast_model)}</p></div><div className="rounded-xl border border-border bg-surface p-4"><p className="text-xs text-text-muted">Deployment gate</p><p className="mt-1 font-semibold text-primary">{statusLabel(evidenceViewModel.deploymentGate)}</p></div></div><details className="rounded-xl border border-border bg-surface p-4"><summary className="cursor-pointer font-semibold text-primary">Technical IDs, artifact identities, and hashes</summary><dl className="mt-4 space-y-3 text-xs text-secondary"><div><dt className="text-text-muted">Run ID</dt><dd className="break-all font-mono">{provenance.run_id}</dd></div><div><dt className="text-text-muted">Manifest SHA-256</dt><dd className="break-all font-mono">{provenance.manifest_sha256}</dd></div><div><dt className="text-text-muted">Formula registry SHA-256</dt><dd className="break-all font-mono">{provenance.formula_registry_sha256}</dd></div><div><dt className="text-text-muted">Deployment profile SHA-256</dt><dd className="break-all font-mono">{provenance.deployment_profile_sha256}</dd></div></dl></details></div>;
}

export default function EvidenceTabs() {
  return <Tabs items={[{id:"dataset",label:"Dataset Validation",content:<DatasetValidation/>},{id:"suitability",label:"Model Suitability",content:<ModelSuitability/>},{id:"forecast",label:"Forecast Evaluation",content:<ForecastEvaluation/>},{id:"explainability",label:"Explainability",content:<Explainability/>},{id:"provenance",label:"Provenance",content:<Provenance/>},{id:"limitations",label:"Limitations",content:<ValidationLimitations/>}]} />;
}
