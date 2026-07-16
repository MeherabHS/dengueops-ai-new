import { MapPin, Building2, Database, FlaskConical, Users } from "lucide-react";

const ROLES = [
  {
    icon: <MapPin className="h-6 w-6" />,
    title: "Public Health Officials",
    subtitle: "Primary operational users",
    uses: [
      "Zone priority ranking and exposure indices",
      "Simulated vector-control planning suggestions",
      "Area-level surge risk and growth factor",
      "Early warning based on 14-day forecast",
    ],
    accent: "border-sky-200 bg-sky-50",
    iconBg: "bg-sky-100 text-sky-700",
    badgeColor: "bg-sky-100 text-sky-700",
  },
  {
    icon: <Building2 className="h-6 w-6" />,
    title: "Hospital Administrators",
    subtitle: "Facility readiness users",
    uses: [
      "NS1/RDT kit and IV fluid depletion timeline",
      "Projected bed load and bed gap estimates",
      "Facility-level priority and action directives",
      "Supply reorder threshold alerts",
    ],
    accent: "border-indigo-200 bg-indigo-50",
    iconBg: "bg-indigo-100 text-indigo-700",
    badgeColor: "bg-indigo-100 text-indigo-700",
  },
  {
    icon: <Database className="h-6 w-6" />,
    title: "MIS / Data Officers",
    subtitle: "Technical pipeline operators",
    uses: [
      "Run analytics pipeline when data is updated",
      "Validate CSV inputs against data contracts",
      "Monitor pipeline run logs and step outputs",
      "Maintain facility and inventory configuration",
    ],
    accent: "border-slate-200 bg-slate-50",
    iconBg: "bg-slate-200 text-slate-700",
    badgeColor: "bg-slate-200 text-slate-600",
  },
  {
    icon: <FlaskConical className="h-6 w-6" />,
    title: "Technical Evaluators",
    subtitle: "IEEE judges · Researchers",
    uses: [
      "Review model validation metrics (MAE, RMSE, MAPE)",
      "Inspect baseline comparisons and chronological split",
      "Examine uncertainty methodology and limitations",
      "Assess pipeline architecture and assumption transparency",
    ],
    accent: "border-violet-200 bg-violet-50",
    iconBg: "bg-violet-100 text-violet-700",
    badgeColor: "bg-violet-100 text-violet-700",
  },
  {
    icon: <Users className="h-6 w-6" />,
    title: "Public / Citizens",
    subtitle: "Future target audience",
    uses: [
      "Not the primary current user group",
      "A simplified public advisory layer is planned",
      "Current prototype targets institutional users",
      "Risk communication outputs may expand in future",
    ],
    accent: "border-slate-200 bg-slate-50 opacity-80",
    iconBg: "bg-slate-100 text-slate-500",
    badgeColor: "bg-slate-100 text-slate-500",
  },
];

export default function UserRolesSection() {
  return (
    <section className="bg-white border-y border-slate-200">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Users & Roles
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Who Is This For?
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-10 leading-relaxed">
          DengueOps AI is designed around specific operational user needs,
          not generic dashboard consumption.
        </p>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {ROLES.map((r) => (
            <div
              key={r.title}
              className={`rounded-xl border ${r.accent} p-5 hover:shadow-md transition-shadow`}
            >
              <div className={`inline-flex items-center justify-center rounded-lg p-2 mb-3 ${r.iconBg}`}>
                {r.icon}
              </div>
              <h3 className="text-sm font-bold text-slate-900 mb-0.5">{r.title}</h3>
              <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold mb-3 ${r.badgeColor}`}>
                {r.subtitle}
              </span>
              <ul className="space-y-1.5">
                {r.uses.map((use) => (
                  <li key={use} className="flex items-start gap-2 text-xs text-slate-600">
                    <span className="text-slate-400 mt-0.5 flex-shrink-0">·</span>
                    {use}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        {/* Operational note */}
        <div className="mt-8 flex items-start gap-3 rounded-xl border border-sky-200 bg-sky-50 px-5 py-4">
          <Building2 className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-sky-800 leading-relaxed">
            <span className="font-semibold">Operational design principle: </span>
            Operational users are not expected to code, clean CSV files, or run scripts during
            an outbreak. The analytics pipeline is maintained by technical/MIS staff, while
            hospital and public health users receive simulated planning suggestions through
            the dashboard.
          </p>
        </div>
      </div>
    </section>
  );
}
