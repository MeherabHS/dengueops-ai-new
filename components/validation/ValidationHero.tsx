import { Info } from "lucide-react";
import { rollingValidation } from "@/lib/demo-data";

const BADGES = [
  rollingValidation.validation_method.replaceAll("_", " "),
  "Baseline comparison",
  "MAE / RMSE / MAPE",
  "Actual vs predicted",
  "Prior-only empirical range",
  `${rollingValidation.fold_count} rolling folds`,
];

export default function ValidationHero() {
  return (
    <div className="mb-12">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Model Evidence
      </p>
      <h1 className="text-3xl font-extrabold text-slate-900 mb-3">
        Rolling-Origin Temporal Validation
      </h1>
      <p className="text-base text-slate-500 max-w-2xl leading-relaxed mb-2 italic">
        &ldquo;Repeated two-week-ahead evaluation with an expanding historical training window.&rdquo;
      </p>
      <p className="text-sm text-slate-600 max-w-2xl leading-relaxed mb-6">
        These results show repeated performance on deterministic synthetic benchmark data.
        They demonstrate pipeline capability, not real-world epidemiological validity.
      </p>

      <div className="flex flex-wrap gap-2 mb-6">
        {BADGES.map((b) => (
          <span
            key={b}
            className="inline-block rounded-full border border-sky-200 bg-sky-50 px-3 py-1 text-[11px] font-semibold text-sky-700"
          >
            {b}
          </span>
        ))}
      </div>

      <div className="flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4 max-w-2xl">
        <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-sky-800 leading-relaxed">
          <span className="font-semibold">For technical evaluators: </span>
          Operational users of DengueOps AI do not need to interpret RMSE or MAE.
          They receive translated preparedness outputs — SDH, bed gap, priority directives.
          This page is for IEEE reviewers, technical evaluators, and researchers.
        </p>
      </div>
    </div>
  );
}
