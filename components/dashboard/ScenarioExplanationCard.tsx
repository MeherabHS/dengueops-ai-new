import { Info, MapPin } from "lucide-react";
import type { SurgeScenarioMeta } from "@/lib/surgeScenarios";

interface Props {
  meta: SurgeScenarioMeta;
}

export default function ScenarioExplanationCard({ meta }: Props) {
  return (
    <div className={`rounded-xl border ${meta.borderColor} ${meta.bgColor} p-4 shadow-sm`}>
      <div className="flex items-start gap-3 mb-3">
        <Info className={`h-4 w-4 flex-shrink-0 mt-0.5 ${meta.color}`} />
        <div className="flex-1">
          <p className={`text-sm font-bold ${meta.color}`}>{meta.label}</p>
          <p className="text-xs text-slate-600 mt-1 leading-relaxed">{meta.explanation}</p>
        </div>
      </div>

      {meta.affectedZones.length > 0 && (
        <div className="mb-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-1.5">
            Affected Zones
          </p>
          <div className="flex flex-wrap gap-1.5">
            {meta.affectedZones.map((z) => (
              <span
                key={z}
                className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-medium text-slate-700"
              >
                <MapPin className="h-2.5 w-2.5 text-slate-400" />
                {z}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="rounded-lg border border-slate-200 bg-white/70 px-3 py-2.5">
        <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-1">
          Operational Implication
        </p>
        <p className="text-xs text-slate-700 leading-relaxed">{meta.operationalImplication}</p>
      </div>

      <p className="mt-3 text-[10px] text-slate-400 italic">
        Scenario simulation modifies existing dashboard outputs for demonstration. It does not retrain the forecasting model.
      </p>
    </div>
  );
}
