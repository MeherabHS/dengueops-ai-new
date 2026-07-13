import { AlertTriangle, CheckCircle2, XCircle, Quote } from "lucide-react";
import { rollingValidation as rv } from "@/lib/demo-data";
import { candidateModelComparison as comparison } from "@/lib/demo-data";

const LIMITATIONS = [
  "Trained and evaluated on controlled synthetic weekly Dhaka South demonstration data. Zone-level spatial allocation uses a synthetic heuristic, not official sub-district surveillance.",
  "The available synthetic history is insufficient to establish stable generalisation to real outbreak cycles.",
  "No real hospital-level validation — dengue bed capacity, occupancy, and inventory data are illustrative.",
  "No ward-level or sub-zone spatial outcome validation — zone allocation is heuristic, not calibrated.",
  "The empirical range is temporally evaluated on synthetic residuals; it is not a prediction interval or probability guarantee.",
  "The aggregate-MAE winner is result-driven and is not a universal claim about the best dengue forecasting model.",
  "Random Forest has limited extrapolation ability; materially different datasets require a new dataset-specific suitability assessment.",
  "Real deployment would require official surveillance data, clinical validation, and institutional partnerships.",
];

const PROVES = [
  "The pipeline supports chronological backtesting with time-based train/test separation.",
  "Naive and Moving Average baselines are compared systematically against ML output.",
  "Model errors (MAE, RMSE, MAPE) are quantified and reported transparently.",
  "Forecast output can be converted into structured uncertainty scenarios.",
  "The dashboard can surface model evidence to technical evaluators.",
];

const DOES_NOT_PROVE = [
  "Does not prove clinical validity or epidemiological accuracy.",
  "Does not prove official public health deployment readiness.",
  "Does not validate real facility stock levels or bed capacity.",
  "Does not claim algorithmic novelty in the forecasting method.",
  "Does not demonstrate performance on real Dhaka South outbreak data.",
];

export default function ValidationLimitations() {
  return (
    <div className="space-y-12">

      {/* Limitations */}
      <section id="limitations" className="mb-4">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Known Limitations
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Limitations of the Current Validation
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-6 leading-relaxed">
          The following limitations are acknowledged transparently as part of the prototype validation design.
        </p>
        <div className="space-y-2.5">
          {[...rv.limitations, ...LIMITATIONS].map((lim, i) => (
            <div key={i} className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-3">
              <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-amber-800 leading-relaxed">{lim}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-bold text-slate-900 mb-2">Importance Stability</h2>
        <p className="text-xs text-slate-600">Native importance stability is aggregated across {rv.fold_count} fitted fold estimators.</p>
        <p className="text-xs text-amber-700 mt-2">Permutation stability: {rv.permutation_stability_status}. P0.4 holdout permutation diagnostics remain available separately and unchanged.</p>
      </section>
      <section className="rounded-xl border border-amber-200 bg-amber-50 p-5">
        <h2 className="text-lg font-bold text-amber-900 mb-2">Candidate Comparison Boundary</h2>
        <p className="text-xs text-amber-800">{comparison.warning ?? comparison.message}</p>
        <p className="text-xs text-amber-800 mt-2">Comparison winner: {comparison.comparison_selected_model ?? "not run"}; active model: {comparison.current_forecast_model}; adoption: {comparison.adoption_status}. Forecast uncertainty uses prior-only synthetic temporal residual evaluation; legacy RMSE values remain planning scenarios only.</p>
      </section>

      {/* Proves / Does Not Prove */}
      <section id="proves">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Interpretation Guidance
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          What Validation Proves / Does Not Prove
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-6 leading-relaxed">
          Clear framing for technical evaluators and IEEE reviewers.
        </p>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
            <p className="text-xs font-bold text-emerald-700 mb-4 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" /> What It Proves
            </p>
            <ul className="space-y-2.5">
              {PROVES.map((p, i) => (
                <li key={i} className="flex items-start gap-2.5 text-xs text-emerald-800 leading-relaxed">
                  <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 mt-0.5 text-emerald-600" />
                  {p}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border border-red-200 bg-red-50 p-5 shadow-sm">
            <p className="text-xs font-bold text-red-700 mb-4 flex items-center gap-2">
              <XCircle className="h-4 w-4" /> What It Does Not Prove
            </p>
            <ul className="space-y-2.5">
              {DOES_NOT_PROVE.map((p, i) => (
                <li key={i} className="flex items-start gap-2.5 text-xs text-red-800 leading-relaxed">
                  <XCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5 text-red-500" />
                  {p}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Evaluator note */}
      <section id="evaluator-note">
        <div className="rounded-xl border border-[#0f172a] bg-[#0f172a] p-6 shadow-md">
          <div className="flex items-start gap-3 mb-3">
            <Quote className="h-5 w-5 text-sky-400 flex-shrink-0 mt-0.5" />
            <p className="text-sm text-white leading-relaxed">
              This validation layer is included so technical evaluators can inspect model behaviour.
              Operational users do not need to interpret RMSE or MAE directly; they receive translated
              preparedness outputs such as{" "}
              <span className="font-semibold text-sky-300">SDH</span>,{" "}
              <span className="font-semibold text-sky-300">bed gap</span>, and{" "}
              <span className="font-semibold text-sky-300">priority directives</span>.
            </p>
          </div>
          <p className="text-[11px] text-slate-400 ml-8">
            Portfolio / Evaluator Note — DengueOps AI · IEEE ICADHI 2025
          </p>
        </div>
      </section>
    </div>
  );
}
