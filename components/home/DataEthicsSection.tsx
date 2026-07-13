import { ShieldCheck, Eye, FlaskConical, Building2, CheckCircle2 } from "lucide-react";

const PRIVACY_POINTS = [
  {
    icon: <ShieldCheck className="h-5 w-5 text-emerald-600" />,
    title: "No patient-level data used",
    desc: "All analytics run on aggregated epi-week case counts and area-level climate data. No individual records, identifiers, or clinical data are collected or processed.",
  },
  {
    icon: <FlaskConical className="h-5 w-5 text-sky-600" />,
    title: "Aggregated and synthetic data only",
    desc: "Where real surveillance data is not available, synthetic demonstration data is generated to illustrate pipeline behaviour. Data generation scripts are fully reproducible.",
  },
  {
    icon: <Building2 className="h-5 w-5 text-indigo-600" />,
    title: "Real facility names as public-sector anchors only",
    desc: "Real public hospital names (DMCH, SSMC, Mugda General, NIBPS) are used only as spatial anchors where publicly available. General bed capacities reference public figures.",
  },
  {
    icon: <Eye className="h-5 w-5 text-amber-600" />,
    title: "Dengue-specific values are synthetic",
    desc: "Dengue-specific bed allocation, current occupancy, NS1/RDT stock, IV fluid stock, and daily consumption values are synthetic demonstration values — not real clinical data.",
  },
  {
    icon: <CheckCircle2 className="h-5 w-5 text-emerald-600" />,
    title: "Outputs are advisory — human review required",
    desc: "All directives, alerts, and readiness scores are decision-support aids. No autonomous operational actions are triggered. Human review is explicitly required.",
  },
];

export default function DataEthicsSection() {
  return (
    <section className="bg-[#0f172a] text-white">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-400 mb-2">
          Privacy & Ethics
        </p>
        <h2 className="text-2xl font-bold text-white mb-2">
          Privacy-Safe Prototype Design
        </h2>
        <p className="text-sm text-sky-300 max-w-2xl mb-10 leading-relaxed">
          DengueOps AI is designed for use under public health data constraints.
          No patient data is required, collected, or processed.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 mb-8">
          {PRIVACY_POINTS.map((p) => (
            <div
              key={p.title}
              className="rounded-xl border border-slate-700 bg-slate-800/60 p-5 hover:border-sky-700 transition-colors"
            >
              <div className="mb-3">{p.icon}</div>
              <h3 className="text-sm font-bold text-white mb-1">{p.title}</h3>
              <p className="text-xs text-slate-400 leading-relaxed">{p.desc}</p>
            </div>
          ))}
        </div>

        {/* Exact required note */}
        <div className="rounded-xl border border-sky-800 bg-sky-950/50 px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-sky-400 mb-2">
            Data Credibility Statement
          </p>
          <p className="text-sm text-sky-200 leading-relaxed">
            Facility names and general bed-capacity anchors are based on public/government references
            where available. Dengue-specific bed allocation, current occupancy, NS1/RDT stock,
            IV fluid stock, and consumption values are{" "}
            <span className="font-semibold text-sky-100">synthetic demonstration values</span>.
          </p>
        </div>
      </div>
    </section>
  );
}
