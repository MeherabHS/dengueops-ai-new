import { ArrowDown, Database, GitMerge, FlaskConical, TrendingUp, Layers, MapPin, BedDouble, Zap } from "lucide-react";

const STEPS = [
  {
    id: "A",
    icon: <Database className="h-5 w-5" />,
    label: "Data Inputs",
    color: "border-slate-300 bg-white",
    iconBg: "bg-slate-100 text-slate-700",
    explanation: "Weekly dengue cases, climate variables, zone exposure proxies, facility readiness data, and inventory assumptions.",
    output: "dengue_cases.csv · climate_data.csv · zones.json · facilities.json · inventory.json",
  },
  {
    id: "B",
    icon: <GitMerge className="h-5 w-5" />,
    label: "Feature Engineering",
    color: "border-sky-200 bg-sky-50",
    iconBg: "bg-sky-100 text-sky-700",
    explanation: "Creates lagged climate features, autoregressive case trends, rolling means, growth rates, and seasonality signals.",
    output: "data/model_features.csv — 29 engineered features per epi week",
  },
  {
    id: "C",
    icon: <FlaskConical className="h-5 w-5" />,
    label: "Temporal Backtesting",
    color: "border-indigo-200 bg-indigo-50",
    iconBg: "bg-indigo-100 text-indigo-700",
    explanation: "Runs the governed 68-fold rolling-origin comparison across seven frozen candidates. The legacy 80/20 split remains diagnostic-only.",
    output: "data/validation_metrics.json · data/model_comparison.json",
  },
  {
    id: "D",
    icon: <TrendingUp className="h-5 w-5" />,
    label: "Forecasting",
    color: "border-sky-200 bg-sky-50",
    iconBg: "bg-sky-100 text-sky-700",
    explanation: "The adopted RandomForestRegressor is refitted on all labelled rows for the 14-day demonstration forecast.",
    output: "data/forecast_output.json — forecast_cases, growth_factor, forecast_growth_category, experimental_growth_score",
  },
  {
    id: "E",
    icon: <Layers className="h-5 w-5" />,
    label: "Uncertainty Scenarios",
    color: "border-violet-200 bg-violet-50",
    iconBg: "bg-violet-100 text-violet-700",
    explanation: "Evaluates a prior-only expanding absolute-residual empirical range and keeps legacy planning scenarios separate.",
    output: "forecast_uncertainty.json + compact forecast reference + preparedness_scenarios",
  },
  {
    id: "F",
    icon: <MapPin className="h-5 w-5" />,
    label: "Spatial Exposure Allocation",
    color: "border-amber-200 bg-amber-50",
    iconBg: "bg-amber-100 text-amber-700",
    explanation: "Allocates city-level forecast cases to zones using a composite spatial exposure heuristic weighted by density, vulnerability, facility pressure, and mobility.",
    output: "Zone-level case allocations and priority scores for each scenario",
  },
  {
    id: "G",
    icon: <BedDouble className="h-5 w-5" />,
    label: "Facility Readiness Modelling",
    color: "border-orange-200 bg-orange-50",
    iconBg: "bg-orange-100 text-orange-700",
    explanation: "Computes SDH for each consumable per facility under forecast-adjusted demand. Projects bed load using LOS logic. Calculates bed gap.",
    output: "Per-facility SDH (NS1/RDT, IV Fluid), bed_gap_expected/worst",
  },
  {
    id: "H",
    icon: <Zap className="h-5 w-5" />,
    label: "Operational Directives",
    color: "border-emerald-200 bg-emerald-50",
    iconBg: "bg-emerald-100 text-emerald-700",
    explanation: "Translates risk and readiness outputs into facility-level preparedness directives: reorder supplies, activate beds, prepare referral protocols, prioritise vector-control response.",
    output: "data/directives.json — 11 facility directives with inventory alerts and simulated planning suggestions",
  },
];

export default function PipelineOverview() {
  return (
    <section id="pipeline" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Pipeline Overview
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Methodology Pipeline Overview
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        Eight sequential stages convert raw surveillance and climate inputs into
        facility-level operational directives.
      </p>

      <div className="space-y-2">
        {STEPS.map((step, i) => (
          <div key={step.id}>
            <div className={`rounded-xl border ${step.color} px-5 py-4 shadow-sm`}>
              <div className="flex items-start gap-4">
                {/* Step indicator */}
                <div className="flex flex-col items-center gap-1 flex-shrink-0">
                  <div className={`flex items-center justify-center w-8 h-8 rounded-lg ${step.iconBg}`}>
                    {step.icon}
                  </div>
                  <span className="text-[10px] font-bold text-slate-400">{step.id}</span>
                </div>
                {/* Content */}
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-slate-900 mb-1">{step.label}</p>
                  <p className="text-xs text-slate-600 leading-relaxed mb-2">{step.explanation}</p>
                  <p className="text-[10px] font-mono text-slate-400 bg-slate-100/70 rounded px-2 py-1 inline-block">
                    → {step.output}
                  </p>
                </div>
              </div>
            </div>
            {i < STEPS.length - 1 && (
              <div className="flex justify-start pl-9">
                <ArrowDown className="h-4 w-4 text-slate-300" />
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
