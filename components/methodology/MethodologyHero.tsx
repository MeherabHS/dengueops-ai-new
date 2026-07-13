import { Info } from "lucide-react";

const BADGES = [
  "Lag-aware forecasting",
  "Temporal backtesting",
  "Temporal empirical range",
  "Spatial exposure allocation",
  "SDH engine",
  "LOS-based bed pressure",
  "Human-in-the-loop",
];

export default function MethodologyHero() {
  return (
    <div className="mb-12">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Technical Documentation
      </p>
      <h1 className="text-3xl font-extrabold text-slate-900 mb-3">Methodology</h1>
      <p className="text-base text-slate-500 max-w-2xl leading-relaxed mb-5 italic">
        &ldquo;From lag-aware dengue forecasting to operational preparedness intelligence.&rdquo;
      </p>
      <p className="text-sm text-slate-600 max-w-2xl leading-relaxed mb-6">
        DengueOps AI does not claim a novel forecasting algorithm. Its contribution is the{" "}
        <span className="font-semibold text-slate-800">operational decision-support layer</span>{" "}
        that converts outbreak forecasts into supply depletion timelines, bed pressure estimates,
        uncertainty scenarios, and zone-level preparedness priorities.
      </p>

      {/* Badges */}
      <div className="flex flex-wrap gap-2 mb-6">
        {BADGES.map((b) => (
          <span
            key={b}
            className="inline-block rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-[11px] font-semibold text-sky-700"
          >
            {b}
          </span>
        ))}
      </div>

      {/* Framing note */}
      <div className="rounded-xl border border-[#1e3a5f] bg-[#0f172a] px-5 py-4 max-w-2xl">
        <p className="text-sm font-semibold text-white mb-1.5">
          Audience note
        </p>
        <p className="text-xs text-sky-300 leading-relaxed">
          RMSE values, MAE comparisons, and model evidence are included for technical evaluators
          and IEEE reviewers. Operational users — public health officials and hospital
          administrators — receive translated preparedness recommendations through the dashboard&apos;s
          role-based views, not raw model metrics.
        </p>
      </div>

      {/* Positioning callout */}
      <div className="mt-4 flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-5 py-3 max-w-2xl">
        <Info className="h-4 w-4 text-sky-500 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-sky-800 leading-relaxed">
          <span className="font-semibold">Core positioning: </span>
          The operational decision-support layer is the primary contribution —
          not proof that the selected Random Forest is superior on real Dhaka data.
        </p>
      </div>
    </div>
  );
}
