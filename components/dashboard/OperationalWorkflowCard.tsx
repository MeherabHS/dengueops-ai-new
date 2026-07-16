import { Database, Cpu, LayoutDashboard, UserCheck, CalendarClock, ChevronRight, Info } from "lucide-react";
import clsx from "clsx";

// ── Workflow step definition ───────────────────────────────────────────────

interface WorkflowStep {
  id: string;
  number: number;
  title: string;
  owner: string;
  ownerRole: "technical" | "operational";
  icon: React.ReactNode;
  bullets: string[];
  accentClass: string;
  iconBgClass: string;
}

const WORKFLOW_STEPS: WorkflowStep[] = [
  {
    id: "sources",
    number: 1,
    title: "Data Sources",
    owner: "External systems",
    ownerRole: "technical",
    icon: <Database className="h-5 w-5" />,
    bullets: [
      "DGHS / IEDCR weekly epi aggregate data",
      "Bangladesh Meteorological Dept. climate data",
      "DSCC facility inventory & bed occupancy feeds",
    ],
    accentClass: "border-slate-300",
    iconBgClass: "bg-slate-100 text-slate-600",
  },
  {
    id: "ingestion",
    number: 2,
    title: "Scheduled Ingestion",
    owner: "MIS / Data Officer",
    ownerRole: "technical",
    icon: <CalendarClock className="h-5 w-5" />,
    bullets: [
      "Weekly automated or manual CSV import",
      "Schema validation against data contract",
      "Deduplication and quality flagging",
    ],
    accentClass: "border-violet-300",
    iconBgClass: "bg-violet-100 text-violet-700",
  },
  {
    id: "pipeline",
    number: 3,
    title: "Analytics Pipeline",
    owner: "Technical / Automated",
    ownerRole: "technical",
    icon: <Cpu className="h-5 w-5" />,
    bullets: [
      "analytics/run_pipeline.py (30–60 s)",
      "Feature engineering → selected Random Forest → RF-bound sensitivity",
      "Operational engine → Directives JSON",
    ],
    accentClass: "border-sky-300",
    iconBgClass: "bg-sky-100 text-sky-700",
  },
  {
    id: "dashboard",
    number: 4,
    title: "Dashboard Alerts",
    owner: "Auto-served to all roles",
    ownerRole: "technical",
    icon: <LayoutDashboard className="h-5 w-5" />,
    bullets: [
      "Pre-computed JSON — zero wait for users",
      "Zone priorities, SDH timelines, bed gaps",
      "Simulated planning suggestions per role",
    ],
    accentClass: "border-emerald-300",
    iconBgClass: "bg-emerald-100 text-emerald-700",
  },
  {
    id: "decision",
    number: 5,
    title: "Human Decision & Action",
    owner: "Hospital / PH / City Corp",
    ownerRole: "operational",
    icon: <UserCheck className="h-5 w-5" />,
    bullets: [
      "Review alerts, not raw data or code",
      "Authorise reorders, bed activation, referrals",
      "Confirm vector-control deployment",
    ],
    accentClass: "border-orange-300",
    iconBgClass: "bg-orange-100 text-orange-700",
  },
];

// ── Sub-components ────────────────────────────────────────────────────────

function StepCard({ step, isLast }: { step: WorkflowStep; isLast: boolean }) {
  return (
    <div className="flex flex-col items-stretch sm:flex-row sm:items-start gap-0">
      {/* Step box */}
      <div
        className={clsx(
          "flex-1 rounded-xl border-2 bg-white p-4 shadow-sm min-w-0",
          step.accentClass
        )}
      >
        <div className="flex items-start gap-3">
          <div className={clsx("rounded-lg p-2 flex-shrink-0", step.iconBgClass)}>
            {step.icon}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs font-bold text-slate-400">
                Step {step.number}
              </span>
              {step.ownerRole === "technical" ? (
                <span className="rounded-full bg-violet-100 px-1.5 py-0.5 text-[10px] font-medium text-violet-700">
                  Technical staff
                </span>
              ) : (
                <span className="rounded-full bg-orange-100 px-1.5 py-0.5 text-[10px] font-medium text-orange-700">
                  Operational staff
                </span>
              )}
            </div>
            <p className="text-sm font-semibold text-slate-800 mt-0.5">{step.title}</p>
            <p className="text-[11px] text-slate-500 mt-0.5 mb-2">{step.owner}</p>
            <ul className="space-y-0.5">
              {step.bullets.map((b, i) => (
                <li key={i} className="flex items-start gap-1.5 text-[11px] text-slate-600">
                  <span className="text-slate-300 mt-0.5 flex-shrink-0">·</span>
                  {b}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>

      {/* Arrow connector (hidden after last step) */}
      {!isLast && (
        <div className="flex items-center justify-center px-1 py-2 sm:py-0 sm:px-2 flex-shrink-0">
          <ChevronRight className="h-5 w-5 text-slate-300 rotate-90 sm:rotate-0" />
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────

interface Props {
  /** Show the full deployment note (true) or compact form (false) */
  compact?: boolean;
}

export default function OperationalWorkflowCard({ compact = false }: Props) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 shadow-sm overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 bg-[#1e3a5f] px-5 py-3">
        <Cpu className="h-4 w-4 text-sky-300 flex-shrink-0" />
        <p className="text-sm font-semibold text-white">
          Operational Workflow — Who Does What
        </p>
        <span className="ml-auto text-xs text-sky-400 hidden sm:block">
          Prototype architecture
        </span>
      </div>

      {/* Workflow steps */}
      <div className="flex flex-col sm:flex-row items-stretch gap-0 p-4">
        {WORKFLOW_STEPS.map((step, idx) => (
          <StepCard
            key={step.id}
            step={step}
            isLast={idx === WORKFLOW_STEPS.length - 1}
          />
        ))}
      </div>

      {/* Required message */}
      <div className="border-t border-slate-200 bg-white px-5 py-4 space-y-3">
        <div className="flex items-start gap-3">
          <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-slate-700 leading-relaxed">
            <span className="font-semibold text-slate-900">
              Operational users are not expected to code, clean CSV files, or run
              scripts during an outbreak.
            </span>{" "}
            The analytics pipeline is maintained by technical/MIS staff, while
            hospital and public health users receive translated action
            simulated planning suggestions.
          </p>
        </div>

        {/* Role legend */}
        <div className="flex flex-wrap gap-3 text-xs">
          <div className="flex items-center gap-1.5">
            <span className="rounded-full bg-violet-100 px-2 py-0.5 font-medium text-violet-700">
              Technical staff
            </span>
            <span className="text-slate-500">
              MIS officers, data analysts, pipeline engineers
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="rounded-full bg-orange-100 px-2 py-0.5 font-medium text-orange-700">
              Operational staff
            </span>
            <span className="text-slate-500">
              Hospital admins, public health officials, city corporation teams
            </span>
          </div>
        </div>
      </div>

      {/* Future deployment note */}
      {!compact && (
        <div className="border-t border-amber-200 bg-amber-50 px-5 py-3 flex items-start gap-2">
          <CalendarClock className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-amber-800 leading-relaxed">
            <span className="font-semibold">Future deployment note:</span>{" "}
            In production, the upload/manual CSV mode would be replaced or
            supplemented by scheduled API/database ingestion from surveillance,
            climate, facility inventory, and hospital readiness systems.
            The dashboard and decision layer remain unchanged — only the
            data ingestion channel is upgraded.
          </p>
        </div>
      )}
    </div>
  );
}
