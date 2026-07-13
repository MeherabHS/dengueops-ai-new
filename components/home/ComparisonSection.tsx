import { CheckCircle2, XCircle } from "lucide-react";

const TYPICAL = [
  "Predicts case counts",
  "Displays time-series charts",
  "Shows risk levels",
  "Stops at outbreak signal",
  "No supply depletion model",
  "No bed pressure estimate",
  "No zone priority framework",
  "No facility-level directives",
];

const DENGUEOPS = [
  "Shows a temporally evaluated empirical forecast range",
  "Keeps Planning Low / Base / High scenarios separate",
  "Estimates NS1/RDT and IV fluid depletion horizon",
  "Projects LOS-based bed pressure per facility",
  "Ranks zones by vulnerability-gated exposure index",
  "Generates facility-level preparedness directives",
  "Provides model validation evidence (MAE, RMSE, MAPE)",
  "Transparent assumptions, human-review required",
];

export default function ComparisonSection() {
  return (
    <section className="bg-white border-y border-slate-200">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Differentiation
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Not Just Another Dengue Prediction Dashboard
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-10 leading-relaxed">
          DengueOps AI extends beyond conventional case-prediction tools by translating
          forecasts into the operational metrics that preparedness decisions require.
        </p>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-2">

          {/* Typical dashboard */}
          <div className="rounded-xl border border-slate-200 bg-slate-50 overflow-hidden">
            <div className="bg-slate-200 px-5 py-3">
              <p className="text-sm font-bold text-slate-700">Typical Dengue Dashboard</p>
              <p className="text-xs text-slate-500 mt-0.5">Case prediction · charts · risk level</p>
            </div>
            <ul className="divide-y divide-slate-100 px-5 py-2">
              {TYPICAL.map((item) => (
                <li key={item} className="flex items-start gap-2.5 py-2.5">
                  <XCircle className="h-4 w-4 text-slate-400 flex-shrink-0 mt-0.5" />
                  <span className="text-xs text-slate-600">{item}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* DengueOps AI */}
          <div className="rounded-xl border border-sky-200 bg-sky-50 overflow-hidden">
            <div className="bg-gradient-to-r from-[#1e3a5f] to-[#0f172a] px-5 py-3">
              <p className="text-sm font-bold text-white">DengueOps AI</p>
              <p className="text-xs text-sky-300 mt-0.5">
                Forecast → preparedness intelligence · decision-support
              </p>
            </div>
            <ul className="divide-y divide-sky-100 px-5 py-2">
              {DENGUEOPS.map((item) => (
                <li key={item} className="flex items-start gap-2.5 py-2.5">
                  <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0 mt-0.5" />
                  <span className="text-xs text-slate-700 font-medium">{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <p className="mt-6 text-[11px] text-slate-400 text-center">
          All outputs are advisory and require human review before any operational action.
          This is a simulation-based prototype, not a deployment-ready system.
        </p>
      </div>
    </section>
  );
}
