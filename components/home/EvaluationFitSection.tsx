import { CheckCircle2 } from "lucide-react";

const CRITERIA = [
  {
    criterion: "Technical Quality",
    tag: "ML · Feature Engineering · Validation",
    desc: "Lagged climate features, chronological train/test split, baseline comparison (naive, moving average), MAE/RMSE/MAPE metrics, uncertainty engine.",
    color: "border-sky-200 bg-sky-50",
    badge: "bg-sky-100 text-sky-700",
  },
  {
    criterion: "Originality",
    tag: "Decision-Support Layer",
    desc: "Forecast-to-preparedness operational layer: SDH supply depletion, LOS bed pressure, zone priority scoring, facility-level directives — not only case prediction.",
    color: "border-indigo-200 bg-indigo-50",
    badge: "bg-indigo-100 text-indigo-700",
  },
  {
    criterion: "Functionality",
    tag: "Working Prototype",
    desc: "Fully working Next.js dashboard visualising forecast, model validation, uncertainty, supply depletion, bed pressure, zone priority, and operational directives.",
    color: "border-emerald-200 bg-emerald-50",
    badge: "bg-emerald-100 text-emerald-700",
  },
  {
    criterion: "Impact",
    tag: "Public Health Preparedness",
    desc: "Supports dengue surge preparedness planning for hospital administrators and public health teams in high-burden urban settings like Dhaka South.",
    color: "border-amber-200 bg-amber-50",
    badge: "bg-amber-100 text-amber-700",
  },
  {
    criterion: "Scalability",
    tag: "Modular Pipeline Design",
    desc: "Modular Python analytics pipeline designed for city-level scale-up. Can expand to other cities, diseases, or real data feeds with minimal architectural changes.",
    color: "border-violet-200 bg-violet-50",
    badge: "bg-violet-100 text-violet-700",
  },
  {
    criterion: "Ethics",
    tag: "Privacy · Transparency · Human-in-the-loop",
    desc: "No patient-level data, explicit assumption disclosure, transparent model limitations, synthetic data labelling, and human-review requirement for all outputs.",
    color: "border-teal-200 bg-teal-50",
    badge: "bg-teal-100 text-teal-700",
  },
];

export default function EvaluationFitSection() {
  return (
    <section className="bg-slate-50 border-y border-slate-200">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Evaluation Alignment
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Designed for ICADHI Track 06
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-10 leading-relaxed">
          How DengueOps AI maps to IEEE ICADHI Track 06: Health Data Analytics &amp; Predictive Systems
          evaluation criteria.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {CRITERIA.map((c) => (
            <div
              key={c.criterion}
              className={`rounded-xl border ${c.color} p-5 hover:shadow-md transition-shadow`}
            >
              <div className="flex items-start justify-between mb-3">
                <h3 className="text-sm font-bold text-slate-900">{c.criterion}</h3>
                <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0" />
              </div>
              <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold mb-3 ${c.badge}`}>
                {c.tag}
              </span>
              <p className="text-xs text-slate-600 leading-relaxed">{c.desc}</p>
            </div>
          ))}
        </div>

        <div className="mt-8 flex items-center justify-center gap-2 text-xs text-slate-400">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
          <span>All criteria addressed within the prototype scope. Deployment limitations are explicitly disclosed.</span>
        </div>
      </div>
    </section>
  );
}
