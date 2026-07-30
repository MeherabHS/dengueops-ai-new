import Tabs from "@/components/ui/Tabs";
import StatusBadge from "@/components/ui/StatusBadge";
import ValidationDesignSection from "@/components/validation/ValidationDesignSection";
import ModelSummaryCards from "@/components/validation/ModelSummaryCards";
import ModelComparisonTable from "@/components/validation/ModelComparisonTable";
import ActualVsPredictedPanel from "@/components/validation/ActualVsPredictedPanel";
import ErrorComparisonPanel from "@/components/validation/ErrorComparisonPanel";
import ValidationLimitations from "@/components/validation/ValidationLimitations";
import FeatureImportanceChart from "@/components/charts/FeatureImportanceChart";
import { historicalBenchmarkEvidence } from "@/lib/demo-data";
import { modelLabel, statusLabel } from "@/lib/status-labels";

function DatasetValidation() {
  return (
    <div>
      <div className="mb-5 rounded-xl border border-informational/25 bg-informational/10 p-4">
        <h3 className="font-semibold text-primary">Historical committed benchmark run</h3>
        <p className="mt-1 text-sm text-secondary">
          This deterministic synthetic benchmark is historical evidence. Uploaded datasets require separate runtime
          dataset validation.
        </p>
      </div>
      <ValidationDesignSection />
    </div>
  );
}

function ModelSuitability() {
  return (
    <div>
      <p className="mb-5 max-w-4xl text-sm text-secondary">
        This comparison applies only to the historical synthetic benchmark and does not establish the current
        runtime assignment authority or suitability for a future upload.
      </p>
      <ModelSummaryCards />
      <ModelComparisonTable />
    </div>
  );
}

function ForecastEvaluation() {
  const metrics = historicalBenchmarkEvidence.comparison.winnerMetrics;
  return (
    <section>
      <p className="text-xs font-semibold uppercase tracking-wider text-accent">Historical benchmark performance</p>
      <h3 className="mt-1 text-xl font-bold text-primary">Historical Random Forest rolling performance</h3>
      <p className="mt-2 text-sm text-secondary">Benchmark evidence only. These metrics are not current outcome monitoring.</p>
      {metrics ? (
        <dl className="mt-4 grid gap-3 sm:grid-cols-3">
          {[
            ["MAE", Number(metrics.mae).toFixed(2)],
            ["RMSE", Number(metrics.rmse).toFixed(2)],
            ["WAPE", Number(metrics.wape).toFixed(2)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-xl border border-border bg-surface p-4">
              <dt className="text-xs text-text-muted">{label}</dt>
              <dd className="mt-1 text-xl font-bold text-primary">{value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </section>
  );
}

function Explainability() {
  const diagnostics = historicalBenchmarkEvidence.featureDiagnostics;
  return (
    <div>
      <div className="mb-5 flex flex-wrap gap-2">
        <StatusBadge label="Historical Random Forest diagnostics" variant="info" />
        <StatusBadge label="Model diagnostic · not causal" variant="warning" />
      </div>
      {diagnostics.status === "generated" ? (
        <>
          <div className="rounded-xl border border-border bg-surface p-4">
            <FeatureImportanceChart data={diagnostics.feature_ranking} />
          </div>
          <p className="mt-3 text-sm text-secondary">{diagnostics.non_causal_warning} {diagnostics.split_warning}</p>
        </>
      ) : <p className="text-secondary">{diagnostics.message}</p>}
    </div>
  );
}

function Provenance() {
  const provenance = historicalBenchmarkEvidence.provenance;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-border bg-surface p-4"><p className="text-xs text-text-muted">Historical run status</p><p className="mt-1 font-semibold text-primary">{statusLabel(historicalBenchmarkEvidence.pipelineRun.status)}</p></div>
        <div className="rounded-xl border border-border bg-surface p-4"><p className="text-xs text-text-muted">Historical benchmark winner</p><p className="mt-1 font-semibold text-primary">{modelLabel(historicalBenchmarkEvidence.comparison.winnerModelId)}</p></div>
        <div className="rounded-xl border border-border bg-surface p-4"><p className="text-xs text-text-muted">Operational classification</p><p className="mt-1 font-semibold text-primary">Benchmark evidence only</p></div>
      </div>
      <details className="rounded-xl border border-border bg-surface p-4">
        <summary className="cursor-pointer font-semibold text-primary">Technical evidence</summary>
        <dl className="mt-4 space-y-3 text-xs text-secondary">
          <div><dt className="text-text-muted">Historical run ID</dt><dd className="break-all font-mono">{provenance.run_id}</dd></div>
          <div><dt className="text-text-muted">Manifest SHA-256</dt><dd className="break-all font-mono">{provenance.manifest_sha256}</dd></div>
          <div><dt className="text-text-muted">Formula registry SHA-256</dt><dd className="break-all font-mono">{provenance.formula_registry_sha256}</dd></div>
          <div><dt className="text-text-muted">Forecasting scope configuration SHA-256</dt><dd className="break-all font-mono">{provenance.deployment_profile_sha256}</dd></div>
        </dl>
      </details>
    </div>
  );
}

function HistoricalCompatibilityEvidence() {
  return (
    <section className="mt-12 rounded-2xl border border-warning/30 bg-surface-raised p-5" aria-labelledby="historical-compatibility-heading">
      <p className="text-xs font-semibold uppercase tracking-wider text-warning">Historical compatibility evidence</p>
      <h2 id="historical-compatibility-heading" className="mt-1 text-2xl font-bold text-primary">Historical Gradient Boosting validation evidence</h2>
      <p className="mt-2 text-sm text-secondary">
        This retained Gradient Boosting evidence is not Histogram gradient boosting, a governed override, a current
        assignment, or current model performance.
      </p>
      <div className="mt-6"><ActualVsPredictedPanel /><ErrorComparisonPanel /></div>
      <details className="mt-4 rounded-lg border border-border bg-surface p-3 text-xs text-secondary">
        <summary className="cursor-pointer font-semibold text-primary">Technical evidence</summary>
        <p className="mt-2 font-mono">Phase: P1.1</p>
        <p className="mt-1 break-all font-mono">{historicalBenchmarkEvidence.historicalGradientBoosting?.model_explainability_artifact_path ?? "data/model_explainability.json"}</p>
      </details>
    </section>
  );
}

export default function EvidenceTabs() {
  return (
    <>
      <Tabs items={[
        { id: "dataset", label: "Dataset Validation", content: <DatasetValidation /> },
        { id: "suitability", label: "Model Suitability", content: <ModelSuitability /> },
        { id: "forecast", label: "Forecast Evaluation", content: <ForecastEvaluation /> },
        { id: "explainability", label: "Explainability", content: <Explainability /> },
        { id: "provenance", label: "Provenance", content: <Provenance /> },
        { id: "limitations", label: "Limitations", content: <ValidationLimitations /> },
      ]} />
      <HistoricalCompatibilityEvidence />
    </>
  );
}
