import { FlaskConical, ExternalLink } from "lucide-react";
import Link from "next/link";
import SectionHeader from "@/components/ui/SectionHeader";
import ModelEvaluationPanel from "@/components/dashboard/ModelEvaluationPanel";
import PipelineStatusPanel from "@/components/dashboard/PipelineStatusPanel";
import CsvUploadPanel from "@/components/dashboard/CsvUploadPanel";
import FeatureImportanceChart from "@/components/charts/FeatureImportanceChart";
import FormulaCard from "@/components/ui/FormulaCard";
import { featureDiagnostics, forecastOutput } from "@/lib/demo-data";

export default function TechnicalValidationView() {
  const uf = forecastOutput.preparedness_scenarios;
  const range = forecastOutput.forecast_uncertainty;

  return (
    <div className="space-y-8">

      {/* ── Audience badge ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2">
        <FlaskConical className="h-4 w-4 text-slate-500 flex-shrink-0" />
        <p className="text-xs text-slate-600">
          <span className="font-semibold text-slate-700">Audience:</span>{" "}
          IEEE ICADHI judges, public health researchers, technical reviewers, and MSc project evaluators.
          This view exposes all model internals, validation evidence, uncertainty methodology,
          and pipeline architecture for full evaluator transparency.
        </p>
      </div>

      {/* ── Model evaluation ─────────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Model Validation & Baseline Comparison"
          subtitle="Chronological time-based backtesting on controlled synthetic Dhaka South demonstration data. Materially different datasets require separate assessment."
        />
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <ModelEvaluationPanel showAvpChart={true} />
        </div>
      </div>

      {/* ── Feature importance ───────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Run-Specific Model Feature Diagnostics"
          subtitle="Permutation and native tree diagnostics generated from the fitted chronological validation-model instance."
        />
        {featureDiagnostics.status === "generated" ? (
          <div className="space-y-3">
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <FeatureImportanceChart data={featureDiagnostics.feature_ranking} />
            </div>
            <div className="grid gap-3 text-xs sm:grid-cols-2">
              <div className="rounded-lg border border-sky-200 bg-sky-50 p-3 text-sky-900">
                <p className="font-semibold">{featureDiagnostics.non_causal_warning}</p>
                <p className="mt-1">{featureDiagnostics.split_warning}</p>
                <p className="mt-1">{featureDiagnostics.stability_warning}</p>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">
                <p>{featureDiagnostics.synthetic_warning}</p>
                <p className="mt-1">{featureDiagnostics.negative_importance_policy}</p>
                <p className="mt-1">{featureDiagnostics.correlated_feature_warning}</p>
              </div>
            </div>
            <p className="text-[11px] text-slate-500">
              Primary: {featureDiagnostics.methods.primary.label} ({featureDiagnostics.methods.primary.scoring}, {featureDiagnostics.methods.primary.repeats} repeats). Secondary: {featureDiagnostics.methods.secondary.label}. Model {featureDiagnostics.model_id} / {featureDiagnostics.model_version}.
            </p>
          </div>
        ) : (
          <div className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600 shadow-sm">
            {featureDiagnostics.message}
          </div>
        )}
      </div>

      {/* ── Uncertainty method ───────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Temporally Evaluated Empirical Forecast Range"
          subtitle="Prior-only expanding absolute-residual quantiles from active Random Forest rolling evidence."
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 mb-4">
          {(["best_case", "expected_case", "worst_case"] as const).map((key) => {
            const sc = uf[key];
            const labels = { best_case: "Planning Low", expected_case: "Planning Base", worst_case: "Planning High" };
            const colors = { best_case: "border-emerald-200 bg-emerald-50", expected_case: "border-sky-200 bg-sky-50", worst_case: "border-red-200 bg-red-50" };
            return (
              <div key={key} className={`rounded-xl border ${colors[key]} p-4`}>
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-1">{labels[key]}</p>
                <p className="text-2xl font-extrabold text-slate-900">{sc.forecast_cases.toLocaleString()}</p>
                <p className="text-xs text-slate-500 mt-1">
                  GF {sc.growth_factor.toFixed(3)}× · {sc.risk_level} · {sc.risk_score}/100
                </p>
              </div>
            );
          })}
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm space-y-3">
          <p className="text-xs font-semibold text-slate-600 uppercase tracking-wider">Methodology</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <FormulaCard
              title="Empirical lower"
              formula={`${range.interval_lower_reported} cases`}
              note="Outward reporting round"
            />
            <FormulaCard
              title="Point forecast"
              formula={`${range.point_forecast_reported} cases`}
              note="Active Random Forest"
            />
            <FormulaCard
              title="Empirical upper"
              formula={`${range.interval_upper_reported} cases`}
              note="Outward reporting round"
            />
          </div>
          <p className="text-[11px] text-slate-500 leading-relaxed pt-2 border-t border-slate-100">
            The 90% nominal empirical target achieved {(range.observed_historical_coverage * 100).toFixed(1)}% historical coverage across {range.evaluated_fold_count} prior-only evaluation folds.
            Targets overlap, the same folds informed model selection, and high-incidence performance may be weaker.
            Historical empirical coverage is not a probability guarantee and this is not a prediction interval.
          </p>
        </div>
      </div>

      {/* ── Priority score formula ───────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Operational Decision Formulas"
          subtitle="How forecast cases are translated into operational metrics."
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <FormulaCard
            title="Growth Factor"
            formula="forecast_cases / cases_rolling_4w"
            note="Surge intensity vs. recent 4-week mean"
          />
          <FormulaCard
            title="Priority Score"
            formula="risk_score x (1 + vulnerability_weight)"
            note="Vulnerability-gated zone urgency"
          />
          <FormulaCard
            title="Stock Depletion (SDH)"
            formula="stock / (baseline_demand x growth_factor)"
            note="Days until supply exhaustion under surge"
          />
          <FormulaCard
            title="Projected Bed Load"
            formula="occupied_beds + (daily_surge x LOS)"
            note="Concurrent dengue bed occupancy"
          />
          <FormulaCard
            title="Bed Gap"
            formula="max(0, projected_load - total_beds)"
            note="Beds required beyond current capacity"
          />
          <FormulaCard
            title="Zone Allocation"
            formula="forecast_cases x normalized_exposure"
            note="Cases distributed by spatial exposure heuristic"
          />
        </div>
      </div>

      {/* ── CSV data readiness ───────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Data Input Readiness"
          subtitle="Validate your own CSV files against the pipeline data contract. No data is transmitted — schema checking is purely client-side."
        />
        <CsvUploadPanel />
      </div>

      {/* ── Pipeline status ───────────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Pipeline Run Status"
          subtitle="Latest execution log from analytics/run_pipeline.py. Shows completed steps, timing, and generated outputs."
        />
        <PipelineStatusPanel />
      </div>

      {/* ── Links to full docs ───────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Full Documentation"
          subtitle="Complete methodology, assumptions, ethics, and roadmap."
        />
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[
            { href: "/validation",   label: "Validation & Backtesting",       desc: "Full backtest results, seasonality drift, baseline comparison" },
            { href: "/methodology",  label: "Methodology",                    desc: "Feature engineering, model selection, operational formulas" },
            { href: "/ethics",       label: "Ethics Statement",               desc: "No patient data, advisory-only, consent and equity principles" },
            { href: "/assumptions",  label: "Assumptions & Limitations",       desc: "What is and is not claimed by this prototype" },
            { href: "/about",        label: "About & Roadmap",                desc: "Project scope, phase roadmap, intended deployment path" },
          ].map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="flex items-start gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm hover:border-sky-300 hover:bg-sky-50 transition-colors group"
            >
              <ExternalLink className="h-4 w-4 text-sky-500 flex-shrink-0 mt-0.5 group-hover:text-sky-600" />
              <div>
                <p className="text-sm font-semibold text-slate-800 group-hover:text-sky-700">
                  {link.label}
                </p>
                <p className="text-xs text-slate-500 mt-0.5">{link.desc}</p>
              </div>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
