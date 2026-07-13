const ASSUMPTIONS = [
  {
    assumption: "Synthetic / demo dengue data",
    why: "Used to demonstrate full analytics pipeline safely without real surveillance data.",
    limitation: "Does not represent official dengue surveillance records.",
    future: "Replace with official aggregated dengue surveillance from DGDA/IEDCR.",
  },
  {
    assumption: "Synthetic facility readiness",
    why: "Real-time bed occupancy and inventory are not publicly available.",
    limitation: "Cannot validate actual hospital shortages or real supply levels.",
    future: "Connect to hospital MIS or authorised facility reporting system.",
  },
  {
    assumption: "Public hospital name anchors",
    why: "Improves geographic realism without fabricating institutional identities.",
    limitation: "Only names and general anchors are real; all readiness values are synthetic.",
    future: "Use validated facility profiles and official capacity data.",
  },
  {
    assumption: "Spatial exposure heuristic",
    why: "City-level forecasts need zone-level allocation; ward-level data unavailable in prototype.",
    limitation: "Not a learned ward-level spatial model; allocation weights are assumed.",
    future: "Use ward-level case data, population density, mobility, and vector indices.",
  },
  {
    assumption: "Prequential absolute-residual empirical range",
    why: "Provides a simple, transparent planning range tied directly to validation error.",
    limitation: "Synthetic, temporally dependent, post-selection evidence; not a probability guarantee or prediction interval.",
    future: "Use quantile regression, bootstrap, or Bayesian forecasting methods.",
  },
  {
    assumption: "LOS-based bed pressure",
    why: "Beds are cumulative resources; dengue admissions accumulate over average stay length.",
    limitation: "Average length of stay is simplified and not validated against real admissions.",
    future: "Use actual diagnosis, admission, and discharge data from facility records.",
  },
  {
    assumption: "Vulnerability-gated priority score",
    why: "Combines forecast risk and structural vulnerability to rank zone response urgency.",
    limitation: "Weights are prototype assumptions, not calibrated with expert consensus.",
    future: "Calibrate with expert input and historical outbreak response outcomes.",
  },
];

export default function CoreAssumptionsTable() {
  return (
    <section id="core-assumptions" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Core Assumptions
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Core Assumptions Table
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        Seven core assumptions underpin the prototype, each with an explicit rationale,
        known limitation, and future improvement path.
      </p>

      <div className="rounded-xl border border-slate-200 overflow-hidden shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead className="bg-[#0f172a]">
              <tr>
                {["Assumption", "Why It Was Used", "Limitation", "Future Improvement"].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-sky-300 whitespace-nowrap"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {ASSUMPTIONS.map((row, i) => (
                <tr key={i} className="hover:bg-slate-50 align-top">
                  <td className="px-4 py-3 font-semibold text-slate-800 min-w-[160px] leading-relaxed">
                    {row.assumption}
                  </td>
                  <td className="px-4 py-3 text-slate-600 min-w-[180px] leading-relaxed">
                    {row.why}
                  </td>
                  <td className="px-4 py-3 min-w-[180px]">
                    <span className="text-amber-700 leading-relaxed">{row.limitation}</span>
                  </td>
                  <td className="px-4 py-3 text-emerald-700 min-w-[180px] leading-relaxed">
                    {row.future}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
