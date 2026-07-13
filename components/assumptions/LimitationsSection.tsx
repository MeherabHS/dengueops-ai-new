import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

const MODELING_LIMITS = [
  "Random Forest was selected and adopted using deterministic synthetic rolling-origin evidence — not claimed as superior on real Dhaka data.",
  "Validation uses demo/synthetic aggregate data, not official surveillance records.",
  "The model cannot prove causal effects of rainfall or humidity on dengue transmission.",
  "Feature importance, if shown, is interpretability only — not causal attribution.",
  "Real deployment would require external validation on real epidemiological data.",
  "Lag structure (14d, 28d) is based on biological reasoning; it is not statistically optimised for Dhaka South specifically.",
];

const SYSTEM_HELPS = [
  "Where risk may rise across epi weeks",
  "Where supply pressure may emerge based on SDH",
  "Where bed pressure may appear based on LOS modelling",
  "Which zones may need vector-control attention",
];

const SYSTEM_DOES_NOT = [
  "Exact procurement orders or quantities",
  "Official emergency declaration triggers",
  "Clinical treatment decisions",
  "Public warning issuance",
  "Final resource deployment decisions",
];

const MISUSE_RISKS = [
  { risk: "Overinterpreting synthetic data as real",         mitigation: "Data mode banners, assumption page, and explicit status labels" },
  { risk: "Treating forecast as certain",                    mitigation: "Uncertainty scenarios (best / expected / worst) shown prominently" },
  { risk: "Ignoring human judgment",                         mitigation: "Human-in-the-loop language throughout all outputs" },
  { risk: "Using outputs for clinical diagnosis",            mitigation: "Explicit no-diagnosis statement in ethics and UI" },
  { risk: "Static vulnerability permanently biasing zones",  mitigation: "Vulnerability-gated priority score design" },
  { risk: "False confidence in synthetic facility values",   mitigation: "Synthetic readiness labels and notes on all facility outputs" },
];

export default function LimitationsSection() {
  return (
    <div className="space-y-14">

      {/* Modeling limits */}
      <section id="modeling-limits">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Modelling Limitations
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-6">
          Modelling Limitations
        </h2>
        <div className="space-y-2.5">
          {MODELING_LIMITS.map((l, i) => (
            <div key={i} className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-3">
              <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
              <p className="text-xs text-amber-800 leading-relaxed">{l}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Decision-support limits */}
      <section id="decision-limits">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Decision-Support Scope
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-6">
          Decision-Support Limitations
        </h2>
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
            <p className="text-xs font-bold text-emerald-700 mb-4 flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4" /> The System Helps Answer
            </p>
            <ul className="space-y-2.5">
              {SYSTEM_HELPS.map((h, i) => (
                <li key={i} className="flex items-start gap-2.5 text-xs text-emerald-800 leading-relaxed">
                  <CheckCircle2 className="h-3.5 w-3.5 flex-shrink-0 mt-0.5 text-emerald-600" />
                  {h}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-xl border border-red-200 bg-red-50 p-5 shadow-sm">
            <p className="text-xs font-bold text-red-700 mb-4 flex items-center gap-2">
              <XCircle className="h-4 w-4" /> The System Does Not Decide
            </p>
            <ul className="space-y-2.5">
              {SYSTEM_DOES_NOT.map((d, i) => (
                <li key={i} className="flex items-start gap-2.5 text-xs text-red-800 leading-relaxed">
                  <XCircle className="h-3.5 w-3.5 flex-shrink-0 mt-0.5 text-red-500" />
                  {d}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Misuse risks */}
      <section id="misuse-risks">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Risk Mitigation
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-6">
          Risk of Misuse and Mitigation
        </h2>
        <div className="rounded-xl border border-slate-200 overflow-hidden shadow-sm">
          <table className="min-w-full text-xs">
            <thead className="bg-[#0f172a]">
              <tr>
                {["Risk", "Mitigation"].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wider text-sky-300">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {MISUSE_RISKS.map((r, i) => (
                <tr key={i} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-amber-700 font-medium leading-relaxed max-w-[240px]">{r.risk}</td>
                  <td className="px-4 py-3 text-slate-600 leading-relaxed">{r.mitigation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
