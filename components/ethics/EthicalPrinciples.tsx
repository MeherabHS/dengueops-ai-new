import {
  UserX,
  Lock,
  Users,
  Stethoscope,
  BarChart2,
  ShieldAlert,
} from "lucide-react";

const PRINCIPLES = [
  {
    icon: UserX,
    color: "border-sky-200 bg-sky-50",
    iconColor: "text-sky-600",
    title: "No Patient-Level Data",
    text: "The prototype does not collect, store, or process identifiable patient-level records. Forecasting and operational outputs are based on aggregated/demo data structures.",
  },
  {
    icon: Lock,
    color: "border-emerald-200 bg-emerald-50",
    iconColor: "text-emerald-600",
    title: "Privacy-Safe Demonstration",
    text: "Facility readiness, inventory, and dengue-specific bed values are synthetic demonstration values. This prevents unauthorised use of sensitive hospital operations data.",
  },
  {
    icon: Users,
    color: "border-violet-200 bg-violet-50",
    iconColor: "text-violet-600",
    title: "Human-in-the-Loop Decision-Making",
    text: "Outputs are advisory. Final decisions remain with public health officials, hospital administrators, and qualified authorities.",
  },
  {
    icon: Stethoscope,
    color: "border-rose-200 bg-rose-50",
    iconColor: "text-rose-600",
    title: "No Clinical Diagnosis",
    text: "The system does not diagnose dengue, recommend individual treatment, or replace clinicians.",
  },
  {
    icon: BarChart2,
    color: "border-amber-200 bg-amber-50",
    iconColor: "text-amber-600",
    title: "Transparent Uncertainty",
    text: "Forecast uncertainty is shown using best, expected, and worst-case scenarios so decision-makers can plan cautiously.",
  },
  {
    icon: ShieldAlert,
    color: "border-slate-200 bg-slate-50",
    iconColor: "text-slate-600",
    title: "Bias and Vulnerability Safeguards",
    text: "The vulnerability-gated priority score prevents static vulnerability factors from permanently dominating response priorities when forecasted dengue risk is low.",
  },
];

export default function EthicalPrinciples() {
  return (
    <section id="principles" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Design Principles
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Ethical Design Principles
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        Six core ethical commitments are embedded in the prototype design.
      </p>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
        {PRINCIPLES.map((p) => {
          const Icon = p.icon;
          return (
            <div
              key={p.title}
              className={`rounded-xl border ${p.color} p-5 shadow-sm`}
            >
              <div className="flex items-center gap-3 mb-3">
                <span className={`flex h-9 w-9 items-center justify-center rounded-lg bg-white border border-slate-100 shadow-sm flex-shrink-0 ${p.iconColor}`}>
                  <Icon className="h-4 w-4" />
                </span>
                <p className="text-sm font-bold text-slate-800 leading-snug">{p.title}</p>
              </div>
              <p className="text-xs text-slate-600 leading-relaxed">{p.text}</p>
            </div>
          );
        })}
      </div>
    </section>
  );
}
