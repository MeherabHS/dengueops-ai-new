import {
  CloudRain,
  GitMerge,
  Layers,
  MapPin,
  BedDouble,
  Zap,
  ArrowRight,
} from "lucide-react";

const STEPS = [
  {
    icon: <CloudRain className="h-5 w-5" />,
    label: "Dengue + Climate Data",
    detail: "Weekly epi case counts, rainfall, temperature, humidity",
    color: "border-slate-300 bg-white",
    iconColor: "text-sky-500",
  },
  {
    icon: <GitMerge className="h-5 w-5" />,
    label: "Lag-Aware Forecasting",
    detail: "14 & 28-day climate lags · governed Random Forest",
    color: "border-slate-300 bg-white",
    iconColor: "text-sky-500",
  },
  {
    icon: <Layers className="h-5 w-5" />,
    label: "Uncertainty Scenarios",
    detail: "Empirical forecast range plus separate planning sensitivities",
    color: "border-slate-300 bg-white",
    iconColor: "text-sky-500",
  },
  {
    icon: <MapPin className="h-5 w-5" />,
    label: "Spatial Exposure Allocation",
    detail: "Zone priority score · vulnerability-gated heuristic",
    color: "border-slate-300 bg-white",
    iconColor: "text-sky-500",
  },
  {
    icon: <BedDouble className="h-5 w-5" />,
    label: "SDH + LOS Bed Pressure",
    detail: "Stock-to-demand horizon · length-of-stay bed load",
    color: "border-slate-300 bg-white",
    iconColor: "text-sky-500",
  },
  {
    icon: <Zap className="h-5 w-5" />,
    label: "Operational Directives",
    detail: "Per-facility: reorder, activate beds, vector control",
    color: "border-sky-200 bg-sky-50",
    iconColor: "text-sky-600",
  },
];

export default function WorkflowSection() {
  return (
    <section className="bg-white border-y border-slate-200">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Solution
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          From Forecasting to Preparedness Intelligence
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-10 leading-relaxed">
          A Python analytics pipeline converts raw surveillance and climate data into
          operational readiness outputs — each step building on the last.
        </p>

        {/* Horizontal flow — wraps on mobile */}
        <div className="flex flex-wrap items-start gap-2">
          {STEPS.map((step, i) => (
            <div key={step.label} className="flex items-start gap-2">
              <div
                className={`rounded-xl border ${step.color} px-4 py-3 shadow-sm min-w-[140px] max-w-[180px]`}
              >
                <span className={`${step.iconColor} mb-1.5 block`}>{step.icon}</span>
                <p className="text-xs font-bold text-slate-800 leading-snug mb-0.5">
                  {step.label}
                </p>
                <p className="text-[10px] text-slate-400 leading-snug">{step.detail}</p>
              </div>
              {i < STEPS.length - 1 && (
                <ArrowRight className="h-4 w-4 text-slate-300 flex-shrink-0 mt-4" />
              )}
            </div>
          ))}
        </div>

        {/* Positioning quote */}
        <div className="mt-10 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-1.5">
            Core Positioning
          </p>
          <blockquote className="text-sm text-sky-900 italic leading-relaxed border-l-4 border-sky-400 pl-4">
            &ldquo;DengueOps AI does not claim a novel forecasting algorithm. Its contribution is
            the operational decision-support layer that converts lag-aware outbreak forecasts
            into uncertainty-aware preparedness metrics and public health action priorities.&rdquo;
          </blockquote>
        </div>
      </div>
    </section>
  );
}
