import { AlertTriangle, TrendingUp, Package, DatabaseZap } from "lucide-react";

const PROBLEMS = [
  {
    icon: <AlertTriangle className="h-5 w-5 text-red-500" />,
    title: "Outbreak signals are recognised late",
    desc: "Surge pressure is often visible only after case load has already exceeded normal bed utilisation, leaving insufficient lead time for procurement or redeployment.",
  },
  {
    icon: <Package className="h-5 w-5 text-orange-500" />,
    title: "Supply shortfalls during peak weeks",
    desc: "Hospitals may exhaust NS1/RDT kits and IV fluids when demand spikes. Without stock-to-demand modelling, reorder decisions arrive after the critical window.",
  },
  {
    icon: <DatabaseZap className="h-5 w-5 text-orange-500" />,
    title: "Fragmented surveillance, climate, and inventory data",
    desc: "Preparedness planning requires integrating dengue case counts, climate signals, facility capacity, and inventory — data that typically sits in separate systems.",
  },
  {
    icon: <TrendingUp className="h-5 w-5 text-amber-500" />,
    title: "Conventional dashboards stop at case prediction",
    desc: "Existing dengue prediction tools forecast case counts but do not translate forecasts into supply depletion timelines, bed pressure estimates, or facility-level directives.",
  },
];

export default function ProblemSection() {
  return (
    <section className="bg-slate-50 border-y border-slate-200">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-red-600 mb-2">
          The Problem
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Dengue Response Is Often Reactive
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-10 leading-relaxed">
          In data-scarce urban health settings like Dhaka South, the gap between
          outbreak signals and operational response can cause preventable
          supply shortfalls and bed capacity crises.
        </p>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {PROBLEMS.map((p) => (
            <div
              key={p.title}
              className="flex gap-4 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <div className="flex-shrink-0 mt-0.5">{p.icon}</div>
              <div>
                <h3 className="text-sm font-bold text-slate-800 mb-1">{p.title}</h3>
                <p className="text-xs text-slate-500 leading-relaxed">{p.desc}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Emphasis box */}
        <div className="mt-8 flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 px-5 py-4">
          <AlertTriangle className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-red-800 leading-relaxed">
            <span className="font-semibold">Key gap: </span>
            Forecast data is not being converted into supply or bed-load projections
            at the facility level. DengueOps AI is built to close this specific gap.
          </p>
        </div>
      </div>
    </section>
  );
}
