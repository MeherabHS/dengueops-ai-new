const DATA_ROWS = [
  { element: "Facility names",               status: "anchor",    note: "Real public anchors where available + synthetic local units" },
  { element: "General bed capacity",          status: "anchor",    note: "Public reference anchor where available / synthetic where unavailable" },
  { element: "Dengue-specific bed allocation",status: "synthetic", note: "Synthetic demonstration values only" },
  { element: "Current dengue occupancy",      status: "synthetic", note: "Synthetic demonstration values only" },
  { element: "NS1 / RDT stock",               status: "synthetic", note: "Synthetic demonstration values only" },
  { element: "IV fluid stock",                status: "synthetic", note: "Synthetic demonstration values only" },
  { element: "Baseline daily consumption",    status: "synthetic", note: "Synthetic demonstration values only" },
  { element: "Dengue case trends",            status: "demo",      note: "Synthetic/demo aggregate — not official surveillance" },
  { element: "Climate values",               status: "demo",      note: "Synthetic/demo or public-style aggregate values" },
  { element: "Patient-level records",         status: "not-used",  note: "Not collected, processed, or stored" },
];

const STATUS_CONFIG: Record<string, { label: string; style: string }> = {
  anchor:    { label: "Public Anchor",    style: "bg-sky-100 text-sky-700 border-sky-200" },
  synthetic: { label: "Synthetic",        style: "bg-amber-100 text-amber-700 border-amber-200" },
  demo:      { label: "Demo / Aggregate", style: "bg-orange-100 text-orange-700 border-orange-200" },
  "not-used":{ label: "Not Used",         style: "bg-emerald-100 text-emerald-700 border-emerald-200" },
};

export default function DataBoundaryTable() {
  return (
    <section id="data-boundary" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Data Boundaries
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        What Is Real vs Synthetic?
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-4 leading-relaxed">
        A clear breakdown of each data element used in the prototype.
      </p>

      {/* Legend */}
      <div className="flex flex-wrap gap-2 mb-6">
        {Object.entries(STATUS_CONFIG).map(([k, v]) => (
          <span key={k} className={`inline-block rounded-full border px-3 py-0.5 text-[10px] font-semibold ${v.style}`}>
            {v.label}
          </span>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 overflow-hidden shadow-sm">
        <table className="min-w-full text-xs">
          <thead className="bg-[#0f172a]">
            <tr>
              {["Data Element", "Prototype Status", "Details"].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-sky-300">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {DATA_ROWS.map((row) => {
              const cfg = STATUS_CONFIG[row.status];
              return (
                <tr key={row.element} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-medium text-slate-800">{row.element}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold ${cfg.style}`}>
                      {cfg.label}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-slate-500 leading-relaxed">{row.note}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Spatial formula note */}
      <div className="mt-8">
        <p className="text-sm font-semibold text-slate-700 mb-3">Spatial Exposure Heuristic</p>
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <p className="text-xs text-slate-600 mb-4 leading-relaxed">
            The prototype forecasts dengue at city level and allocates expected cases to
            zones using a spatial exposure heuristic — not a learned spatial epidemiological model.
          </p>
          <div className="rounded-lg bg-slate-50 border border-slate-200 px-4 py-3 font-mono text-xs text-slate-700 mb-4">
            <p className="font-semibold text-slate-500 text-[10px] uppercase tracking-wider mb-2">Exposure Index Formula</p>
            <p>Exposure Index =</p>
            <p className="ml-4">Population Share &times; 0.40</p>
            <p className="ml-4">+ Density Weight &times; 0.30</p>
            <p className="ml-4">+ Facility Pressure Weight &times; 0.20</p>
            <p className="ml-4">+ Mobility Corridor Weight &times; 0.10</p>
          </div>
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5 leading-relaxed">
            This is not a learned spatial epidemiological model. It is a transparent allocation
            mechanism used because ward-level dengue surveillance data may not be available
            in the prototype context.
          </p>
        </div>
      </div>
    </section>
  );
}
