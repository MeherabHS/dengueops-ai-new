import {
  TrendingUp,
  FlaskConical,
  Layers,
  Package,
  BedDouble,
  Zap,
} from "lucide-react";

const MODULES = [
  {
    icon: <TrendingUp className="h-6 w-6" />,
    title: "Lag-Aware Forecasting",
    tag: "analytics/forecast_model.py",
    desc: "Uses 14- and 28-day climate lags, case trends, and seasonality to generate a short-term synthetic demonstration forecast with the governed Random Forest selected in P1.2A.",
    accent: "border-sky-200 bg-sky-50/60",
    iconColor: "text-sky-600 bg-sky-100",
  },
  {
    icon: <FlaskConical className="h-6 w-6" />,
    title: "Temporal Backtesting",
    tag: "analytics/validation_backtest.py",
    desc: "Uses chronological (time-based) train/test splitting, baseline comparison against naive and moving-average models, and reports MAE, RMSE, and MAPE to evaluate model behaviour.",
    accent: "border-indigo-200 bg-indigo-50/60",
    iconColor: "text-indigo-600 bg-indigo-100",
  },
  {
    icon: <Layers className="h-6 w-6" />,
    title: "Forecast Uncertainty",
    tag: "analytics/uncertainty_engine.py",
    desc: "Shows one prior-only synthetic empirical forecast range while preserving separate legacy planning scenarios. Not a prediction interval or probability guarantee.",
    accent: "border-violet-200 bg-violet-50/60",
    iconColor: "text-violet-600 bg-violet-100",
  },
  {
    icon: <Package className="h-6 w-6" />,
    title: "Supply Depletion Horizon",
    tag: "analytics/operational_engine.py",
    desc: "Estimates how many days NS1/RDT kits and IV fluids may last under forecast-adjusted demand using a stock-to-demand horizon (SDH) model per facility.",
    accent: "border-amber-200 bg-amber-50/60",
    iconColor: "text-amber-600 bg-amber-100",
  },
  {
    icon: <BedDouble className="h-6 w-6" />,
    title: "LOS-Based Bed Pressure",
    tag: "analytics/operational_engine.py",
    desc: "Projects bed pressure using length-of-stay logic rather than treating beds as consumables. Outputs projected bed load and bed gap per facility under each scenario.",
    accent: "border-orange-200 bg-orange-50/60",
    iconColor: "text-orange-600 bg-orange-100",
  },
  {
    icon: <Zap className="h-6 w-6" />,
    title: "Operational Directives",
    tag: "analytics/operational_engine.py",
    desc: "Translates risk and readiness outputs into recommendations: reorder NS1/RDT kits, reorder IV fluids, activate additional beds, prepare referral protocol, prioritise vector-control response.",
    accent: "border-emerald-200 bg-emerald-50/60",
    iconColor: "text-emerald-600 bg-emerald-100",
  },
];

export default function CoreModulesSection() {
  return (
    <section className="bg-slate-50 border-y border-slate-200">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          System Architecture
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Core System Modules
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-10 leading-relaxed">
          Six Python analytics modules, each producing structured JSON outputs
          consumed by the Next.js dashboard.
        </p>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {MODULES.map((m) => (
            <div
              key={m.title}
              className={`rounded-xl border ${m.accent} p-5 hover:shadow-md transition-shadow`}
            >
              <div className={`inline-flex items-center justify-center rounded-lg p-2 mb-3 ${m.iconColor}`}>
                {m.icon}
              </div>
              <h3 className="text-sm font-bold text-slate-900 mb-1">{m.title}</h3>
              <p className="text-[10px] font-mono text-slate-400 mb-2">{m.tag}</p>
              <p className="text-xs text-slate-600 leading-relaxed">{m.desc}</p>
            </div>
          ))}
        </div>

        <p className="mt-8 text-[11px] text-slate-400 text-center">
          All modules produce synthetic demonstration outputs.
          Results illustrate pipeline behaviour, not deployment-grade epidemiological accuracy.
        </p>
      </div>
    </section>
  );
}
