import { AlertTriangle, ArrowRight } from "lucide-react";
import { rollingValidation as rv } from "@/lib/demo-data";
import { candidateModelComparison as comparison } from "@/lib/demo-data";

const flow = [
  ["Historical training data", `${rv.initial_training_window}-row initial history`],
  ["One-row label embargo", "Unavailable future target excluded"],
  ["Weekly forecast origin", `${rv.fold_count} deterministic folds`],
  ["Unseen target", `${rv.horizon_weeks} weeks ahead`],
  ["Expanded history", `${rv.step_weeks}-week step`],
];

export default function ValidationDesignSection() {
  const facts = [
    ["Primary method", rv.validation_method.replaceAll("_", " ")],
    ["Fold count", String(rv.fold_count)],
    ["Initial history", `${rv.initial_training_window} rows`],
    ["Forecast horizon", `${rv.horizon_weeks} weeks`],
    ["Step", `${rv.step_weeks} week`],
    ["Features", "18 canonical features"],
  ];
  return (
    <section id="design" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">Validation Design</p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">Expanding-Window Rolling Origins</h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        Each fold trains on eligible historical rows, embargoes the row whose two-week target is not yet
        available, and evaluates the next weekly origin. Training history then expands by one week.
      </p>
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white p-4 shadow-sm mb-8">
        {flow.map(([label, detail], index) => <div key={label} className="flex items-center gap-2">
          <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
            <p className="text-[11px] font-semibold text-slate-800">{label}</p><p className="text-[10px] text-slate-400">{detail}</p>
          </div>{index < flow.length - 1 && <ArrowRight className="h-3.5 w-3.5 text-slate-300" />}
        </div>)}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6 mb-6">
        {facts.map(([label, value]) => <div key={label} className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">{label}</p>
          <p className="text-xs font-semibold text-slate-800 leading-snug">{value}</p>
        </div>)}
      </div>
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-3">
        <AlertTriangle className="h-4 w-4 text-amber-600 mt-0.5" />
        <p className="text-xs text-amber-800 leading-relaxed">
          Label policy: {rv.label_availability_policy}. Real reporting publication delays and revision vintages
          are not modeled yet. Results use deterministic synthetic benchmark data and do not establish real-world Dhaka performance.
        </p>
      </div>
      <p className="mt-4 text-xs text-slate-600">Candidate comparison status: {comparison.model_selection_status}. Seven fixed candidates use these same fold descriptors; preprocessing is fitted inside each fold.</p>
    </section>
  );
}
