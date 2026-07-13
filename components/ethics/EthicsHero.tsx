import { ShieldCheck } from "lucide-react";

const BADGES = [
  "No patient-level data",
  "Synthetic operational data",
  "Human-in-the-loop",
  "Advisory outputs",
  "No diagnosis",
  "Transparent assumptions",
];

export default function EthicsHero() {
  return (
    <div className="mb-12">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Responsible AI
      </p>
      <h1 className="text-3xl font-extrabold text-slate-900 mb-3">
        Ethics &amp; Responsible Use
      </h1>
      <p className="text-base text-slate-500 max-w-2xl leading-relaxed mb-2 italic">
        &ldquo;Privacy-safe, human-in-the-loop decision support for dengue preparedness.&rdquo;
      </p>
      <p className="text-sm text-slate-600 max-w-2xl leading-relaxed mb-6">
        DengueOps AI is designed as a public health preparedness prototype, not a diagnostic
        or autonomous decision-making tool. It uses aggregated and synthetic demonstration
        data to show how outbreak forecasts can be translated into readiness alerts and
        action priorities without processing patient-level information.
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

      <div className="flex items-start gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-5 py-4 max-w-2xl">
        <ShieldCheck className="h-4 w-4 text-emerald-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-emerald-800 leading-relaxed">
          <span className="font-semibold">Design intent: </span>
          This prototype demonstrates a privacy-safe, transparent, and human-in-the-loop
          approach to AI-enabled public health preparedness.
          It prioritises responsible simulation over unsupported claims of live deployment.
        </p>
      </div>
    </div>
  );
}
