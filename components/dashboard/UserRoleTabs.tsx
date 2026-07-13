import { Shield, Building2, Users, FlaskConical } from "lucide-react";
import clsx from "clsx";

export type UserRole = "operational" | "facility" | "public" | "technical";

interface RoleDefinition {
  id: UserRole;
  label: string;
  audience: string;
  icon: React.ReactNode;
}

const ROLES: RoleDefinition[] = [
  {
    id: "operational",
    label: "Operational Command",
    audience: "Public health officials · Vector-control teams",
    icon: <Shield className="h-4 w-4" />,
  },
  {
    id: "facility",
    label: "Facility Readiness",
    audience: "Hospital administrators · Diagnostic centers",
    icon: <Building2 className="h-4 w-4" />,
  },
  {
    id: "public",
    label: "Public Advisory",
    audience: "Citizen-facing communications (preview)",
    icon: <Users className="h-4 w-4" />,
  },
  {
    id: "technical",
    label: "Technical Validation",
    audience: "Judges · Researchers · Analysts",
    icon: <FlaskConical className="h-4 w-4" />,
  },
];

interface Props {
  activeRole: UserRole;
  onRoleChange: (role: UserRole) => void;
}

export default function UserRoleTabs({ activeRole, onRoleChange }: Props) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Tab strip */}
      <div className="flex overflow-x-auto scrollbar-hide" role="tablist">
        {ROLES.map((role, idx) => {
          const isActive = role.id === activeRole;
          return (
            <button
              key={role.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => onRoleChange(role.id)}
              className={clsx(
                "flex flex-1 min-w-[140px] flex-col items-center gap-1 px-4 py-3 text-center text-xs transition-all border-b-2 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-500",
                isActive
                  ? "border-b-sky-600 bg-sky-50 text-sky-700 font-semibold"
                  : "border-b-transparent text-slate-500 hover:bg-slate-50 hover:text-slate-700",
                idx < ROLES.length - 1 && "border-r border-slate-100"
              )}
            >
              <span
                className={clsx(
                  "rounded-md p-1.5",
                  isActive ? "bg-sky-100 text-sky-700" : "bg-slate-100 text-slate-400"
                )}
              >
                {role.icon}
              </span>
              <span className="font-medium leading-tight">{role.label}</span>
              <span
                className={clsx(
                  "text-[10px] leading-tight hidden sm:block",
                  isActive ? "text-sky-500" : "text-slate-400"
                )}
              >
                {role.audience}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
