import { Info } from "lucide-react";
import { dashboardSummary } from "@/lib/demo-data";

export default function UncertaintyLinkageSection() {
  const range = dashboardSummary.uncertainty;
  const planning = dashboardSummary.preparedness_scenarios;
  return (
    <section id="uncertainty-linkage" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">Uncertainty evidence</p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">Temporally Evaluated Empirical Forecast Range</h2>
      <p className="text-sm text-slate-500 max-w-3xl mb-8 leading-relaxed">
        Each evaluated fold uses only absolute Random Forest residuals from earlier folds. The committed compact projection records {range.evaluated_fold_count} historical evaluation folds. Targets overlap and the same fold set informed model selection.
      </p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-8">
        {[
          ["Nominal target", `${(range.nominal_coverage * 100).toFixed(0)}% empirical`],
          ["Historical coverage", `${(range.observed_historical_coverage * 100).toFixed(4)}%`],
          ["Covered / evaluated", range.covered_fold_count === undefined ? `Not projected / ${range.evaluated_fold_count}` : `${range.covered_fold_count} / ${range.evaluated_fold_count}`],
          ["Interval status", "Not a prediction interval"],
        ].map(([label, value]) => <div key={label} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p><p className="text-xs font-bold text-slate-800">{value}</p></div>)}
      </div>
      <div className="mb-5 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-slate-200 bg-white p-3"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Warm-up folds</p><p className="text-sm font-bold text-slate-800">{range.calibration_warmup_fold_count ?? "Not projected"}</p></div>
        <div className="rounded-lg border border-slate-200 bg-white p-3"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Average width</p><p className="text-sm font-bold text-slate-800">{range.average_interval_width === undefined ? "Not projected" : `${range.average_interval_width.toFixed(4)} cases`}</p></div>
        <div className="rounded-lg border border-slate-200 bg-white p-3"><p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Lower / upper misses</p><p className="text-sm font-bold text-slate-800">{range.lower_miss_count === undefined || range.upper_miss_count === undefined ? "Not projected" : `${range.lower_miss_count} / ${range.upper_miss_count}`}</p></div>
      </div>
      <div className="rounded-xl border border-sky-200 bg-sky-50 p-4 mb-5">
        <p className="text-sm font-semibold text-sky-900">Current empirical range: {range.interval_lower_reported}–{range.interval_upper_reported} cases around the {range.point_forecast_reported}-case forecast</p>
        <p className="mt-1 text-xs text-sky-800">High-incidence and rising-period performance may be weaker. Historical empirical coverage is not a probability guarantee.</p>
      </div>
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 mb-5">
        <p className="text-sm font-semibold text-amber-900">Planning sensitivity scenarios remain separate</p>
        <p className="mt-1 text-xs text-amber-800">Operational compatibility continues to use {planning.best_case.forecast_cases} / {planning.expected_case.forecast_cases} / {planning.worst_case.forecast_cases}. These legacy RF RMSE planning values are uncalibrated and do not represent the empirical forecast range.</p>
      </div>
      <div className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-5 py-4"><Info className="h-4 w-4 text-slate-500 mt-0.5"/><p className="text-xs text-slate-600">Synthetic rolling evidence is not real-world Dhaka calibration. The range is not a probability statement or guarantee.</p></div>
    </section>
  );
}
