import { AlertTriangle } from "lucide-react";

const BADGES = [
  "Synthetic demonstration data",
  "Spatial heuristic",
  "Synthetic empirical range",
  "Public facility anchors",
  "Advisory output",
  "Real deployment requires validation",
];

export default function AssumptionsHero() {
  return (
    <div className="mb-12">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Transparency
      </p>
      <h1 className="text-3xl font-extrabold text-slate-900 mb-3">
        Assumptions &amp; Limitations
      </h1>
      <p className="text-base text-slate-500 max-w-2xl leading-relaxed mb-2 italic">
        &ldquo;Transparent boundaries for interpreting the DengueOps AI prototype.&rdquo;
      </p>
      <p className="text-sm text-slate-600 max-w-2xl leading-relaxed mb-6">
        This page documents the assumptions behind the prototype. DengueOps AI is designed
        to demonstrate decision-support logic under data-scarce conditions, not to claim
        validated real-world deployment accuracy.
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

      <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 max-w-2xl">
        <AlertTriangle className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-amber-800 leading-relaxed">
          <span className="font-semibold">For evaluators: </span>
          All assumptions are made explicit so reviewers can assess the prototype design
          without misinterpreting it as a validated live system.
        </p>
      </div>
    </div>
  );
}
