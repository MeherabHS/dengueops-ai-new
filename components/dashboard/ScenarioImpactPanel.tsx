import { TrendingUp, Minus, AlertTriangle } from "lucide-react";
import type { SurgeKey, ZoneSurgeData, SurgeScenarioMeta } from "@/lib/surgeScenarios";

const RISK_BADGE: Record<string, string> = {
  Critical: "bg-red-100 text-red-700 border-red-200",
  High:     "bg-orange-100 text-orange-700 border-orange-200",
  Moderate: "bg-yellow-100 text-yellow-700 border-yellow-200",
  Routine:  "bg-slate-100 text-slate-600 border-slate-200",
};

interface Props {
  surgeKey: SurgeKey;
  meta: SurgeScenarioMeta;
  zones: ZoneSurgeData[];
}

export default function ScenarioImpactPanel({ surgeKey, meta, zones }: Props) {
  const isNormal = surgeKey === "normal";

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-5 py-3 border-b border-slate-100 flex items-center justify-between gap-3">
        <div>
          <p className="text-sm font-bold text-slate-800">
            Zone Impact — {meta.label}
          </p>
          <p className="text-[11px] text-slate-400 mt-0.5">
            {isNormal
              ? "Baseline expected-case values. No surge modifier applied."
              : "Surge-adjusted values shown. Baseline in parentheses."}
          </p>
        </div>
        {!isNormal && (
          <span className="flex-shrink-0 flex items-center gap-1 rounded-full bg-sky-100 border border-sky-200 px-2 py-0.5 text-[10px] font-semibold text-sky-700">
            <AlertTriangle className="h-3 w-3" /> Simulation overlay
          </span>
        )}
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-50 border-b border-slate-100">
            <tr>
              {["Zone", "Priority (0–100)", "Proj. Cases", "Risk Level", isNormal ? "" : "Change"].map((h) => (
                <th
                  key={h}
                  className="px-4 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-slate-400"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-50">
            {zones.map((z) => {
              const isAffected = z.modifier > 1.0;
              const priorityDelta = z.adjusted_priority - z.baseline_priority;
              const casesDelta = +(z.adjusted_cases - z.baseline_cases).toFixed(1);
              return (
                <tr
                  key={z.zone_name}
                  className={isAffected && !isNormal ? "bg-sky-50/50" : "hover:bg-slate-50"}
                >
                  <td className="px-4 py-3 font-medium text-slate-800">
                    {z.zone_name}
                    {isAffected && !isNormal && (
                      <span className="ml-1.5 inline-block rounded-full bg-sky-100 px-1.5 py-0.5 text-[9px] font-semibold text-sky-700">
                        ×{z.modifier.toFixed(2)}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono">
                    <span className={`font-bold ${z.adjusted_priority >= 76 ? "text-red-600" : z.adjusted_priority >= 51 ? "text-orange-600" : "text-slate-700"}`}>
                      {z.adjusted_priority}
                    </span>
                    {!isNormal && isAffected && (
                      <span className="text-slate-400 text-[10px] ml-1">({z.baseline_priority})</span>
                    )}
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-700">
                    {z.adjusted_cases.toFixed(0)}
                    {!isNormal && isAffected && (
                      <span className="text-slate-400 text-[10px] ml-1">({z.baseline_cases.toFixed(0)})</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-full border px-2 py-0.5 text-[10px] font-semibold ${RISK_BADGE[z.adjusted_risk] ?? RISK_BADGE.Routine}`}>
                      {z.adjusted_risk}
                    </span>
                  </td>
                  {!isNormal && (
                    <td className="px-4 py-3">
                      {isAffected ? (
                        <div className="flex flex-col gap-0.5">
                          <span className="flex items-center gap-1 text-[10px] font-semibold text-amber-700">
                            <TrendingUp className="h-3 w-3" />
                            +{priorityDelta} pts / +{casesDelta} cases
                          </span>
                        </div>
                      ) : (
                        <span className="flex items-center gap-1 text-[10px] text-slate-400">
                          <Minus className="h-3 w-3" /> No change
                        </span>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer disclaimer */}
      <div className="px-5 py-2.5 border-t border-slate-100 bg-slate-50">
        <p className="text-[10px] text-slate-400 leading-relaxed">
          Priority scores (0–100): Routine 0–25 | Moderate 26–50 | High 51–75 | Critical 76+.
          Scenario simulation is a what-if overlay and does not retrain the forecasting model.
          Values are prototype simulation overlays — not official epidemiological forecasts.
        </p>
      </div>
    </div>
  );
}
