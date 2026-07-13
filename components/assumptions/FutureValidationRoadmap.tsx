import { Quote } from "lucide-react";

const ROADMAP_STEPS = [
  {
    step: 1,
    title: "Replace demo data with official surveillance",
    detail: "Use official aggregated dengue surveillance data from DGDA, IEDCR, or city corporation epidemiology unit.",
  },
  {
    step: 2,
    title: "Validate climate lags against historical outcomes",
    detail: "Test whether 14-day and 28-day lag assumptions hold against real dengue outbreak timelines in Dhaka.",
  },
  {
    step: 3,
    title: "Validate uncertainty on untouched real data",
    detail: "Re-evaluate the frozen temporal range policy on post-selection Dhaka observations before any deployment claim.",
  },
  {
    step: 4,
    title: "Validate facility readiness logic",
    detail: "Use authorised hospital data to validate dengue bed capacity, occupancy, and inventory estimates.",
  },
  {
    step: 5,
    title: "Test zone prioritisation against historical response",
    detail: "Assess whether the spatial exposure heuristic aligns with documented outbreak zones and vector-control deployments.",
  },
  {
    step: 6,
    title: "Add secure scheduled ingestion pipeline",
    detail: "Automate data ingestion from authorised sources with error handling, logging, and data freshness checks.",
  },
  {
    step: 7,
    title: "Add access control and audit logs",
    detail: "Implement role-based access, session management, and immutable audit logs for all data and model actions.",
  },
  {
    step: 8,
    title: "Develop simplified public advisory layer",
    detail: "Create a public-facing output layer that presents risk levels in plain language without exposing facility or model details.",
  },
];

export default function FutureValidationRoadmap() {
  return (
    <div className="space-y-14">

      <section id="roadmap">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Future Work
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Future Validation Roadmap
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
          Eight prioritised steps required to move from prototype towards real operational deployment.
        </p>

        <div className="space-y-3">
          {ROADMAP_STEPS.map((s) => (
            <div
              key={s.step}
              className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm"
            >
              <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-sky-100 text-sm font-bold text-sky-700">
                {s.step}
              </span>
              <div>
                <p className="text-sm font-semibold text-slate-800 mb-0.5">{s.title}</p>
                <p className="text-xs text-slate-500 leading-relaxed">{s.detail}</p>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Final Assumption Summary */}
      <section id="final-summary">
        <div className="rounded-xl border border-[#0f172a] bg-[#0f172a] p-6 shadow-md">
          <div className="flex items-start gap-3">
            <Quote className="h-5 w-5 text-sky-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm text-white leading-relaxed mb-2">
                The value of DengueOps AI is not that it already represents a live city-wide
                deployment. Its value is that it demonstrates a{" "}
                <span className="font-semibold text-sky-300">transparent, auditable, and extensible</span>{" "}
                decision-support architecture for converting outbreak forecasts into
                preparedness intelligence.
              </p>
              <p className="text-[11px] text-slate-400">
                Assumptions Summary — DengueOps AI · IEEE ICADHI 2025
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
