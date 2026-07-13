"use client";

import { SURGE_SCENARIOS } from "@/lib/surgeScenarios";
import type { SurgeKey } from "@/lib/surgeScenarios";

interface Props {
  active: SurgeKey;
  onChange: (k: SurgeKey) => void;
}

export default function SurgeScenarioSelector({ active, onChange }: Props) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-2">
        Surge Simulation Scenario — spatial priority overlay
      </p>
      <div className="flex flex-wrap gap-2">
        {SURGE_SCENARIOS.map((s) => {
          const isActive = active === s.key;
          return (
            <button
              key={s.key}
              onClick={() => onChange(s.key)}
              className={`
                rounded-full px-3 py-1.5 text-xs font-semibold border transition-all
                ${isActive
                  ? `${s.bgColor} ${s.borderColor} ${s.color} shadow-sm`
                  : "bg-white border-slate-200 text-slate-500 hover:border-slate-400"
                }
              `}
            >
              {s.short}
            </button>
          );
        })}
      </div>
    </div>
  );
}
