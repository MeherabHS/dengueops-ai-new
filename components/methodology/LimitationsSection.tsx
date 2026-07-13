import { Users, AlertTriangle, ArrowRight } from "lucide-react";

const LIMITATIONS = [
  {
    title: "Synthetic / demo data throughout",
    desc: "All case counts, climate values, inventory levels, and bed occupancy figures are synthetically generated. Results demonstrate pipeline behaviour, not real-world epidemiological accuracy.",
  },
  {
    title: "No patient-level data",
    desc: "Only aggregated weekly case totals are used. Individual-level clinical or epidemiological data are not available, collected, or processed in this prototype.",
  },
  {
    title: "Facility readiness and inventory values are simulated",
    desc: "Dengue-specific bed allocations, occupancy figures, NS1/RDT stock, and IV fluid stock are synthetic demonstration values. Real public hospital names are used as spatial anchors only.",
  },
  {
    title: "Zone allocation is a heuristic",
    desc: "Spatial case disaggregation uses a weighted exposure index, not a validated spatial epidemiology model. Zone case counts are advisory approximations, not precision estimates.",
  },
  {
    title: "Uncertainty band is not fully probabilistic",
    desc: "The empirical range uses prior-only synthetic RF residuals. Historical coverage is not a probability guarantee; legacy RMSE scenarios remain planning compatibility only.",
  },
  {
    title: "Real deployment requires validated official data and integration",
    desc: "Operational use would require validated DGHS/IEDCR surveillance data, actual facility MIS integration, institutional governance, and deployment infrastructure beyond this prototype scope.",
  },
];

const ROADMAP = [
  { label: "Real surveillance data connection",    desc: "DGHS/IEDCR validated case feed" },
  { label: "Scheduled data ingestion",             desc: "Automated weekly pipeline execution" },
  { label: "Calibrated probabilistic forecasting", desc: "Conformal prediction or bootstrapped ensemble" },
  { label: "Ward-level spatial modelling",         desc: "Validated geospatial population and mobility data" },
  { label: "Facility MIS integration",             desc: "Live bed occupancy and stock system" },
  { label: "Public advisory layer",                desc: "Simplified risk communication for citizens" },
  { label: "Dashboard deployment with access control", desc: "Role-based auth for hospital / PH staff" },
];

export default function LimitationsSection() {
  return (
    <div className="space-y-14">

      {/* ── 13. Human-in-the-Loop Design ──────────────────────────────── */}
      <section id="human-in-loop">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Human-in-the-Loop
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Human-in-the-Loop Design
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
          All DengueOps AI outputs are advisory. No operational actions are triggered
          automatically. Final decisions remain with qualified public health and
          hospital authorities.
        </p>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 mb-6">
          {[
            { title: "Outputs are advisory, not diagnostic",     desc: "The system does not diagnose dengue. It generates preparedness signals for human review by qualified health professionals." },
            { title: "No autonomous decision-making",            desc: "No directives trigger automatic orders, procurement, or operational actions. All recommendations require explicit human approval." },
            { title: "Technical/MIS staff maintain the pipeline", desc: "Pipeline execution, data validation, and configuration are responsibilities of technical or MIS staff — not operational users." },
            { title: "Operational users receive translated outputs", desc: "Public health officials and hospital administrators receive plain-language recommendations — not RMSE values or raw JSON." },
          ].map((item) => (
            <div key={item.title} className="flex gap-3 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
              <Users className="h-4 w-4 text-emerald-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="text-xs font-bold text-emerald-800 mb-1">{item.title}</p>
                <p className="text-xs text-emerald-700 leading-relaxed">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Required exact sentence */}
        <div className="rounded-xl border border-[#1e3a5f] bg-[#0f172a] px-5 py-4 max-w-2xl">
          <p className="text-sm text-sky-200 leading-relaxed">
            &ldquo;Operational users are not expected to code, clean CSV files, or run scripts
            during an outbreak. The analytics pipeline is maintained by technical/MIS staff,
            while hospital and public health users receive translated action
            recommendations.&rdquo;
          </p>
        </div>
      </section>

      {/* ── 14. Limitations ───────────────────────────────────────────── */}
      <section id="limitations">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Limitations
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Known Limitations
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
          These limitations are disclosed explicitly as part of the prototype&apos;s
          transparency design. They are not deficiencies to be minimised but
          constraints to be clearly communicated to evaluators and users.
        </p>

        <div className="space-y-3">
          {LIMITATIONS.map((l, i) => (
            <div key={l.title} className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
              <div className="flex items-center justify-center w-7 h-7 rounded-full border-2 border-amber-300 bg-amber-50 text-amber-700 text-xs font-bold flex-shrink-0 mt-0.5">
                {i + 1}
              </div>
              <div>
                <p className="text-sm font-bold text-slate-900 mb-1">{l.title}</p>
                <p className="text-xs text-slate-500 leading-relaxed">{l.desc}</p>
              </div>
            </div>
          ))}
        </div>

        <div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
          <AlertTriangle className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-amber-700 leading-relaxed">
            This prototype demonstrates simulation-based decision-support pipeline design
            and forecast-to-preparedness translation logic. It is not a deployment-ready
            system and does not claim clinical or epidemiological validation on real data.
          </p>
        </div>
      </section>

      {/* ── 15. Future Extension ──────────────────────────────────────── */}
      <section id="future">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Future Roadmap
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Future Extension Pathways
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
          The modular Python analytics pipeline is designed to accommodate progressive
          data and capability upgrades without full redesign.
        </p>

        <div className="space-y-2">
          {ROADMAP.map((item, i) => (
            <div key={item.label} className="flex items-start gap-4 rounded-xl border border-slate-200 bg-white px-5 py-3.5 shadow-sm">
              <div className="flex items-center justify-center w-6 h-6 rounded-full bg-sky-100 text-sky-700 text-[11px] font-bold flex-shrink-0 mt-0.5">
                {i + 1}
              </div>
              <div className="flex items-start gap-2 flex-1">
                <p className="text-sm font-semibold text-slate-800">{item.label}</p>
                <ArrowRight className="h-3.5 w-3.5 text-slate-300 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-slate-500">{item.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
