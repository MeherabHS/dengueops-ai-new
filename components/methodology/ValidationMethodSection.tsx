import { Trophy, Info, AlertTriangle } from "lucide-react";
import modelComparisonRaw from "@/data/model_comparison.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const mc = modelComparisonRaw as any;

function periodLabel(p: { epi_year_start: number; epi_week_start: number; epi_year_end: number; epi_week_end: number }) {
  return `${p.epi_year_start} W${p.epi_week_start} → ${p.epi_year_end} W${p.epi_week_end}`;
}

const improvementVsNaive = mc?.models
  ? Math.round((1 - mc.models[2].mae / mc.models[0].mae) * 100)
  : 68;

export default function ValidationMethodSection() {
  const models: { model_key: string; model_name: string; role: string; is_selected: boolean; mae: number; rmse: number; mape: number }[] =
    mc?.models ?? [];

  return (
    <section id="validation" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Temporal Backtesting
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Temporal Backtesting & Baseline Comparison
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        A chronological (time-based) train/test split is used to evaluate model performance
        under realistic conditions — each test prediction uses only data that would have
        been available at that point in time.
      </p>

      {/* Why chronological */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3 mb-8">
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="text-xs font-bold text-red-700 mb-1">❌ Random split (not used)</p>
          <p className="text-xs text-red-600 leading-relaxed">
            Random row shuffling creates future data leakage — test rows may contain
            data from earlier in the series than training rows.
          </p>
        </div>
        <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
          <p className="text-xs font-bold text-emerald-700 mb-1">✓ Chronological split (used)</p>
          <p className="text-xs text-emerald-600 leading-relaxed">
            Train on early epi weeks, test on the final 20%. Every test prediction
            uses only historically available data.
          </p>
        </div>
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-4">
          <p className="text-xs font-bold text-sky-700 mb-1">✓ Baseline comparison (used)</p>
          <p className="text-xs text-sky-600 leading-relaxed">
            A model that cannot beat naive last-week repeat provides no operational
            signal. Baselines establish the minimum useful bar.
          </p>
        </div>
      </div>

      {/* Split metadata */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 mb-8">
        {[
            { label: "Validation Design", value: "One chronological holdout (final 20%)" },
          { label: "Train Rows",        value: `${mc?.train_rows ?? 96} epi weeks` },
          { label: "Test Rows",         value: `${mc?.test_rows ?? 25} epi weeks` },
          { label: "Forecast Target",   value: "Cases +14 days" },
        ].map((m) => (
          <div key={m.label} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{m.label}</p>
            <p className="text-sm font-semibold text-slate-800 mt-0.5">{m.value}</p>
          </div>
        ))}
      </div>

      {mc?.train_period && mc?.test_period && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 mb-8 text-xs">
          <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Train Period</p>
            <p className="text-sm font-medium text-slate-700 mt-0.5 font-mono">{periodLabel(mc.train_period)}</p>
          </div>
          <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Test Period</p>
            <p className="text-sm font-medium text-slate-700 mt-0.5 font-mono">{periodLabel(mc.test_period)}</p>
          </div>
        </div>
      )}

      {/* Model comparison table */}
      <div className="mb-6">
        <p className="text-sm font-semibold text-slate-700 mb-3">
          Model Comparison — Chronological Test Period
        </p>
        <div className="rounded-xl border border-slate-200 overflow-hidden shadow-sm">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                {["Model", "Role", "MAE", "RMSE", "MAPE (%)", ""].map((h) => (
                  <th key={h} className="px-4 py-2.5 text-left font-semibold text-slate-500 uppercase tracking-wider text-[10px]">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {models.map((m) => (
                <tr key={m.model_key} className={m.is_selected ? "bg-sky-50" : ""}>
                  <td className="px-4 py-2.5 font-medium text-slate-800">{m.model_name}</td>
                  <td className="px-4 py-2.5">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                      m.is_selected ? "bg-sky-100 text-sky-700" : "bg-slate-100 text-slate-600"
                    }`}>
                      {m.is_selected ? "Primary ML" : "Baseline"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 font-mono text-slate-700">{m.mae.toFixed(1)}</td>
                  <td className="px-4 py-2.5 font-mono text-slate-700">{m.rmse.toFixed(1)}</td>
                  <td className="px-4 py-2.5 font-mono text-slate-700">{m.mape.toFixed(1)}%</td>
                  <td className="px-4 py-2.5">
                    {m.is_selected && (
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                        <Trophy className="h-3 w-3" /> Best
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Selection rationale */}
      <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4 mb-4">
        <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-semibold text-sky-800 mb-1">Model selection rationale</p>
          <p className="text-xs text-sky-700 leading-relaxed">
            Random Forest was selected under the declared MAE-first rule after completing all 68
            rolling-origin folds without failure, then adopted under P1.2B. The displayed GBR holdout
            remains historical compatibility evidence ({improvementVsNaive}% lower MAE than its naive baseline),
            not active-model performance. No real-world Dhaka superiority is claimed.
          </p>
        </div>
      </div>

      {/* Leakage and notes */}
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
        <p className="text-xs font-semibold text-amber-800 mb-2">Validation methodology notes — research candidate only</p>
        <ul className="space-y-1.5 text-xs text-amber-700">
          {(mc?.notes ?? []).map((note: string, i: number) => (
            <li key={i} className="flex gap-2">
              <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
              {note}
            </li>
          ))}
          {mc?.leakage_prevention && (
            <li className="flex gap-2">
              <AlertTriangle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
              <span><strong>Leakage prevention:</strong> {mc.leakage_prevention}</span>
            </li>
          )}
        </ul>
      </div>
    </section>
  );
}
