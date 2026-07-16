import { XCircle, ArrowRight, Info } from "lucide-react";

const DOES_NOT = [
  "Diagnose dengue.",
  "Recommend individual treatment.",
  "Replace clinical judgment.",
  "Claim access to live hospital stock or bed data.",
  "Automatically trigger public health action.",
  "Provide official public warnings.",
  "Process patient-identifiable data.",
];

const OUTPUT_LAYERS = [
  {
    label: "Technical layer",
    color: "border-slate-200 bg-slate-50",
    labelColor: "text-slate-500",
    items: ["MAE / RMSE", "Forecast uncertainty", "Model comparison", "Feature lags"],
  },
  {
    label: "Operational layer",
    color: "border-sky-200 bg-sky-50",
    labelColor: "text-sky-600",
    items: ["Experimental forecast-growth category", "SDH", "Bed gap", "Planning-priority score", "Simulated planning suggestions"],
  },
  {
    label: "Decision layer",
    color: "border-emerald-200 bg-emerald-50",
    labelColor: "text-emerald-600",
    items: ["Human review", "Facility planning", "Vector-control prioritisation", "Contingency planning"],
  },
];

export default function SafetyBoundaries() {
  return (
    <div className="space-y-14">
      {/* What the system does not do */}
      <section id="safety-boundaries">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Safety Boundaries
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          What the System Does Not Do
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-6 leading-relaxed">
          Clear negative constraints are part of the responsible design.
        </p>

        <div className="space-y-2.5">
          {DOES_NOT.map((item) => (
            <div
              key={item}
              className="flex items-start gap-3 rounded-xl border border-rose-200 bg-rose-50 px-5 py-3"
            >
              <XCircle className="h-4 w-4 text-rose-500 flex-shrink-0 mt-0.5" />
              <p className="text-xs font-medium text-rose-800">It does not — {item}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Responsible Output Design */}
      <section id="output-design">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Output Translation
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Responsible Output Design
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-6 leading-relaxed">
          Technical model outputs are translated into operational preparedness metrics
          before reaching decision-makers.
        </p>

        <div className="flex flex-wrap items-start gap-3 mb-6">
          {OUTPUT_LAYERS.map((layer, i) => (
            <div key={layer.label} className="flex items-start gap-3">
              <div className={`rounded-xl border ${layer.color} p-4 min-w-[160px]`}>
                <p className={`text-[10px] font-bold uppercase tracking-wider mb-2 ${layer.labelColor}`}>
                  {layer.label}
                </p>
                <ul className="space-y-1">
                  {layer.items.map((it) => (
                    <li key={it} className="text-xs text-slate-700">· {it}</li>
                  ))}
                </ul>
              </div>
              {i < OUTPUT_LAYERS.length - 1 && (
                <ArrowRight className="h-4 w-4 text-slate-300 flex-shrink-0 mt-8" />
              )}
            </div>
          ))}
        </div>

        <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4 max-w-2xl">
          <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-sky-800 leading-relaxed">
            RMSE and model metrics are included for technical validation and evaluator
            transparency; operational users receive translated preparedness outputs rather
            than raw model diagnostics.
          </p>
        </div>
      </section>
    </div>
  );
}
