import { Database, Search, Building2, TreePine, FlaskConical, Quote } from "lucide-react";

const ROLES = [
  {
    icon: Database,
    color: "border-sky-200 bg-sky-50",
    iconColor: "text-sky-600",
    title: "MIS / Data Officer",
    duties: [
      "Maintains the analytics data pipeline",
      "Validates input files before scheduled runs",
      "Runs scheduled pipeline updates",
    ],
  },
  {
    icon: Search,
    color: "border-violet-200 bg-violet-50",
    iconColor: "text-violet-600",
    title: "Public Health Analyst",
    duties: [
      "Reviews forecast behaviour and uncertainty ranges",
      "Checks assumptions and data limitations",
      "Interprets outbreak patterns cautiously",
    ],
  },
  {
    icon: Building2,
    color: "border-amber-200 bg-amber-50",
    iconColor: "text-amber-600",
    title: "Hospital Administrator",
    duties: [
      "Uses readiness alerts for facility planning",
      "Confirms real stock and bed status before taking action",
      "Does not treat synthetic values as definitive",
    ],
  },
  {
    icon: TreePine,
    color: "border-emerald-200 bg-emerald-50",
    iconColor: "text-emerald-600",
    title: "City Corporation / Vector-Control Team",
    duties: [
      "Uses zone priority score as one input among many",
      "Confirms local field conditions before deployment",
      "Does not act on prototype output alone",
    ],
  },
  {
    icon: FlaskConical,
    color: "border-slate-200 bg-slate-50",
    iconColor: "text-slate-600",
    title: "Technical Evaluator",
    duties: [
      "Reviews model validation, limitations, and assumptions",
      "Assesses pipeline design and decision-support logic",
      "Does not evaluate as a live clinical system",
    ],
  },
];

const FUTURE_REQUIREMENTS = [
  "Institutional approval and governance",
  "Official data-sharing agreements",
  "Privacy review and data protection assessment",
  "Facility-level validation of readiness logic",
  "Access control and role-based permissions",
  "Audit logs for all data and forecast actions",
  "Regular model monitoring and recalibration",
  "Public health governance and accountability chain",
  "Clear legal accountability framework",
];

export default function UserResponsibilities() {
  return (
    <div className="space-y-14">
      {/* Role Cards */}
      <section id="user-roles">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          User Roles
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          User Roles and Ethical Responsibilities
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
          Each user role interacts with the prototype in a defined, bounded capacity.
        </p>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {ROLES.map((r) => {
            const Icon = r.icon;
            return (
              <div key={r.title} className={`rounded-xl border ${r.color} p-5 shadow-sm`}>
                <div className="flex items-center gap-3 mb-3">
                  <span className={`flex h-9 w-9 items-center justify-center rounded-lg bg-white border border-slate-100 shadow-sm flex-shrink-0 ${r.iconColor}`}>
                    <Icon className="h-4 w-4" />
                  </span>
                  <p className="text-sm font-bold text-slate-800 leading-snug">{r.title}</p>
                </div>
                <ul className="space-y-1.5">
                  {r.duties.map((d) => (
                    <li key={d} className="text-xs text-slate-600 leading-relaxed">· {d}</li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </section>

      {/* Future Deployment Ethics */}
      <section id="future-ethics">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Future Deployment
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Future Deployment Ethics
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-6 leading-relaxed">
          Real operational deployment of this system would require formal governance and
          institutional safeguards beyond the prototype scope.
        </p>

        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {FUTURE_REQUIREMENTS.map((req, i) => (
            <div
              key={i}
              className="flex items-start gap-2.5 rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm"
            >
              <span className="mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-sky-100 text-[10px] font-bold text-sky-700">
                {i + 1}
              </span>
              <p className="text-xs text-slate-700 leading-relaxed">{req}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Ethics Summary */}
      <section id="ethics-summary">
        <div className="rounded-xl border border-[#0f172a] bg-[#0f172a] p-6 shadow-md">
          <div className="flex items-start gap-3">
            <Quote className="h-5 w-5 text-sky-400 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm text-white leading-relaxed mb-2">
                DengueOps AI demonstrates a privacy-safe, transparent, and human-in-the-loop
                approach to AI-enabled public health preparedness. The prototype prioritises
                responsible simulation over unsupported claims of live deployment.
              </p>
              <p className="text-[11px] text-slate-400">
                Ethics Summary — DengueOps AI · IEEE ICADHI 2025
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
