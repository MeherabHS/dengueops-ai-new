import { ArrowRight, Info } from "lucide-react";

const PROTO_STEPS = [
  { label: "CSV / JSON data files",     sub: "synthetic demo data" },
  { label: "Python analytics pipeline", sub: "manual / scheduled run" },
  { label: "Static dashboard outputs",  sub: "JSON → Next.js frontend" },
];

const FUTURE_STEPS = [
  { label: "Scheduled ingestion",      sub: "automated data feed" },
  { label: "API / database feeds",     sub: "real-time or daily batch" },
  { label: "Automatic pipeline runs",  sub: "triggered by new data" },
  { label: "Access-controlled dashboard", sub: "role-based login" },
  { label: "Audit logs",               sub: "traceability & governance" },
];

export default function OperationalWorkflowAssumption() {
  return (
    <section id="operational-workflow" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Operational Design
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Operational Workflow Assumption
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-6 leading-relaxed">
        The prototype is designed so that operational users are never required to touch
        code, scripts, or data files.
      </p>

      <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4 mb-8 max-w-2xl">
        <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-sky-800 leading-relaxed">
          Operational users are not expected to code, clean CSV files, or run scripts during
          an outbreak. The analytics pipeline is maintained by technical/MIS staff, while
          hospital and public health users receive translated action recommendations.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 mb-8">
        {/* Prototype flow */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-4">
            Current Prototype
          </p>
          <div className="space-y-2">
            {PROTO_STEPS.map((s, i) => (
              <div key={s.label} className="flex items-start gap-2.5">
                <div className="flex flex-col items-center">
                  <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-slate-100 text-[10px] font-bold text-slate-500">
                    {i + 1}
                  </span>
                  {i < PROTO_STEPS.length - 1 && (
                    <span className="mt-1 h-4 w-px bg-slate-200" />
                  )}
                </div>
                <div className="pb-3">
                  <p className="text-xs font-semibold text-slate-800">{s.label}</p>
                  <p className="text-[10px] text-slate-400">{s.sub}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Future production flow */}
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-5 shadow-sm">
          <p className="text-xs font-bold text-sky-600 uppercase tracking-wider mb-4">
            Future Production
          </p>
          <div className="space-y-2">
            {FUTURE_STEPS.map((s, i) => (
              <div key={s.label} className="flex items-start gap-2.5">
                <div className="flex flex-col items-center">
                  <span className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-sky-200 text-[10px] font-bold text-sky-700">
                    {i + 1}
                  </span>
                  {i < FUTURE_STEPS.length - 1 && (
                    <span className="mt-1 h-4 w-px bg-sky-200" />
                  )}
                </div>
                <div className="pb-3">
                  <p className="text-xs font-semibold text-slate-800">{s.label}</p>
                  <p className="text-[10px] text-slate-400">{s.sub}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Role separation note */}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        {[
          { role: "MIS / Data Officer", action: "Runs pipeline updates", color: "bg-slate-100 text-slate-700" },
          { role: "→", action: "", color: "" },
          { role: "Public Health / Hospital Users", action: "Review translated outputs", color: "bg-sky-100 text-sky-700" },
          { role: "→", action: "", color: "" },
          { role: "Decision-Makers", action: "Act with human judgment", color: "bg-emerald-100 text-emerald-700" },
        ].map((item, i) =>
          item.role === "→" ? (
            <ArrowRight key={i} className="h-4 w-4 text-slate-300" />
          ) : (
            <div key={i} className={`rounded-lg px-3 py-2 text-center ${item.color}`}>
              <p className="text-[10px] font-bold">{item.role}</p>
              <p className="text-[10px] opacity-80">{item.action}</p>
            </div>
          )
        )}
      </div>
    </section>
  );
}
