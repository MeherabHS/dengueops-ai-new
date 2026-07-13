import { Info } from "lucide-react";

const DATA_ITEMS = [
  { item: "Dengue case data",            status: "synthetic",  note: "Demo aggregate values for pipeline demonstration." },
  { item: "Climate data",                status: "synthetic",  note: "Synthetic/demo or public-style aggregate values." },
  { item: "Public hospital names",       status: "anchor",     note: "Used as geographic facility anchors where available." },
  { item: "General bed capacity",        status: "anchor",     note: "Public reference anchor where available; synthetic otherwise." },
  { item: "Dengue-specific beds",        status: "synthetic",  note: "Synthetic demonstration values only." },
  { item: "Current dengue occupancy",    status: "synthetic",  note: "Synthetic demonstration values only." },
  { item: "NS1/RDT stock",               status: "synthetic",  note: "Synthetic demonstration values only." },
  { item: "IV fluid stock",              status: "synthetic",  note: "Synthetic demonstration values only." },
  { item: "Baseline daily consumption",  status: "synthetic",  note: "Synthetic demonstration values only." },
  { item: "Patient-level records",       status: "not-used",   note: "Not collected, processed, or stored." },
];

const STATUS_STYLE: Record<string, string> = {
  synthetic: "bg-amber-100 text-amber-700 border-amber-200",
  anchor:    "bg-sky-100   text-sky-700   border-sky-200",
  "not-used": "bg-emerald-100 text-emerald-700 border-emerald-200",
};
const STATUS_LABEL: Record<string, string> = {
  synthetic: "Synthetic / Demo",
  anchor:    "Public Anchor",
  "not-used": "Not Used",
};

export default function DataEthicsSection() {
  return (
    <section id="data-ethics" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Data Ethics
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Data Ethics and Data Boundaries
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        Clear boundaries define what is real, what is anchored from public sources, and
        what is entirely synthetic demonstration data.
      </p>

      <div className="rounded-xl border border-slate-200 overflow-hidden shadow-sm mb-6">
        <table className="min-w-full text-xs">
          <thead className="bg-[#0f172a]">
            <tr>
              {["Data Element", "Status", "Note"].map((h) => (
                <th key={h} className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-sky-300">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {DATA_ITEMS.map((row) => (
              <tr key={row.item} className="hover:bg-slate-50">
                <td className="px-4 py-3 font-medium text-slate-800">{row.item}</td>
                <td className="px-4 py-3">
                  <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold ${STATUS_STYLE[row.status]}`}>
                    {STATUS_LABEL[row.status]}
                  </span>
                </td>
                <td className="px-4 py-3 text-slate-500 leading-relaxed">{row.note}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4">
        <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-sky-800 leading-relaxed">
          <span className="font-semibold">Exact statement: </span>
          Facility names and general bed-capacity anchors are based on public/government
          references where available. Dengue-specific bed allocation, current occupancy,
          NS1/RDT stock, IV fluid stock, and consumption values are
          <span className="font-semibold"> synthetic demonstration values</span>.
        </p>
      </div>
    </section>
  );
}
