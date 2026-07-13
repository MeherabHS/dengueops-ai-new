import { CheckCircle2, AlertTriangle, AlertCircle } from "lucide-react";
import type { Directive } from "@/lib/types";

interface Props {
  directives: Directive[];
}

function AlertIcon({ level }: { level: "Critical" | "Warning" | "ok" }) {
  if (level === "Critical")
    return <AlertCircle className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />;
  if (level === "Warning")
    return <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />;
  return <CheckCircle2 className="h-4 w-4 text-emerald-500 flex-shrink-0 mt-0.5" />;
}

export default function DirectiveTable({ directives }: Props) {
  const sorted = [...directives].sort((a, b) => b.priority_score - a.priority_score);

  return (
    <div className="space-y-4">
      {sorted.map((d) => (
        <div key={d.facility_id} className="overflow-hidden rounded-xl border border-border bg-surface">
          <div className="flex items-center justify-between bg-surface-raised px-4 py-3">
            <div>
              <span className="text-sm font-bold text-white">{d.zone_name}</span>
              <span className="ml-2 text-xs text-sky-300">{d.facility_name}</span>
            </div>
            <span className="text-xs text-sky-200">
              Priority: <strong>{d.priority_score.toFixed(1)}</strong>
              {" · "}
              <span className={d.priority_category === "Critical" ? "text-red-300" : "text-sky-200"}>
                {d.priority_category}
              </span>
            </span>
          </div>
          <div className="px-4 py-3">
            {d.inventory_alerts.length > 0 && (
              <div className="mb-3 space-y-1.5">
                {d.inventory_alerts.map((alert, i) => (
                  <div key={i} className="flex gap-2 text-xs">
                    <AlertIcon level={alert.alert_level} />
                    <span className="text-slate-700">{alert.message}</span>
                  </div>
                ))}
              </div>
            )}
            <ul className="space-y-1">
              {d.recommendations.map((rec, i) => (
                <li key={i} className="flex gap-2 text-xs text-slate-600">
                  <span className="text-sky-600 font-bold shrink-0">{i + 1}.</span>
                  {rec}
                </li>
              ))}
            </ul>
          </div>
        </div>
      ))}
    </div>
  );
}
