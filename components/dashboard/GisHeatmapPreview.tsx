"use client";

import { Info } from "lucide-react";
import type { SurgeKey, ZoneSurgeData } from "@/lib/surgeScenarios";

// ─── Heat colour by priority score ───────────────────────────────────────────

function heatColor(score: number): {
  bg: string; border: string; text: string; badge: string; label: string;
} {
  if (score >= 76) return { bg: "bg-red-100",    border: "border-red-400",    text: "text-red-900",    badge: "bg-red-500 text-white",      label: "Critical" };
  if (score >= 51) return { bg: "bg-orange-100", border: "border-orange-400", text: "text-orange-900", badge: "bg-orange-500 text-white",    label: "High"     };
  if (score >= 26) return { bg: "bg-yellow-100", border: "border-yellow-400", text: "text-yellow-900", badge: "bg-yellow-400 text-yellow-900", label: "Moderate" };
  return            { bg: "bg-slate-100",  border: "border-slate-300",  text: "text-slate-700",  badge: "bg-slate-400 text-white",    label: "Routine"  };
}

// ─── Schematic layout positions ───────────────────────────────────────────────
// Roughly approximates Dhaka South geography as a 3×2 schematic grid.
// NOT geographically accurate — intentionally schematic for prototype.

const LAYOUT: { zone: string; col: string; row: string; wide?: boolean }[] = [
  { zone: "Kamrangirchar",      col: "col-start-1 col-span-1", row: "row-start-2" },
  { zone: "Lalbagh / Hazaribagh", col: "col-start-1 col-span-1", row: "row-start-1" },
  { zone: "Dhanmondi",           col: "col-start-2 col-span-1", row: "row-start-1" },
  { zone: "Mitford / Old Dhaka", col: "col-start-2 col-span-1", row: "row-start-2" },
  { zone: "Jatrabari / Sayedabad", col: "col-start-3 col-span-1", row: "row-start-2" },
];

interface Props {
  zones: ZoneSurgeData[];
  surgeKey: SurgeKey;
}

export default function GisHeatmapPreview({ zones, surgeKey }: Props) {
  const zoneMap = Object.fromEntries(zones.map((z) => [z.zone_name, z]));

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      {/* Header */}
      <div className="flex items-start justify-between mb-4 gap-4">
        <div>
          <p className="text-sm font-bold text-slate-800">
            Zone Priority Heatmap
          </p>
          <p className="text-xs text-slate-500 mt-0.5 italic leading-snug">
            &ldquo;Prototype visualization of spatial priority across five Dhaka South operational zones.&rdquo;
          </p>
        </div>
        <span className="flex-shrink-0 rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-700">
          Schematic · Operational zones only
        </span>
      </div>

      {/* Heat scale legend */}
      <div className="flex flex-wrap gap-2 mb-5">
        {[
          { label: "0–25 Routine",  cls: "bg-slate-400" },
          { label: "26–50 Moderate", cls: "bg-yellow-400" },
          { label: "51–75 High",    cls: "bg-orange-500" },
          { label: "76+ Critical",  cls: "bg-red-500" },
        ].map((l) => (
          <div key={l.label} className="flex items-center gap-1.5">
            <span className={`h-3 w-3 rounded-sm flex-shrink-0 ${l.cls}`} />
            <span className="text-[10px] font-medium text-slate-600">{l.label}</span>
          </div>
        ))}
      </div>

      {/* Schematic grid map */}
      <div className="grid grid-cols-3 grid-rows-2 gap-2.5 min-h-[220px] mb-4">
        {LAYOUT.map(({ zone, col, row }) => {
          const z = zoneMap[zone];
          if (!z) return null;
          const heat = heatColor(z.adjusted_priority);
          const isAffected = z.modifier > 1.0;
          return (
            <div
              key={zone}
              className={`
                relative rounded-xl border-2 p-3 flex flex-col justify-between
                transition-all duration-300
                ${heat.bg} ${heat.border}
                ${col} ${row}
                ${isAffected && surgeKey !== "normal" ? "ring-2 ring-offset-1 ring-sky-400 shadow-md" : ""}
              `}
            >
              {/* Surge highlight badge */}
              {isAffected && surgeKey !== "normal" && (
                <span className="absolute -top-2 -right-2 rounded-full bg-sky-500 border-2 border-white px-1.5 py-0.5 text-[9px] font-bold text-white shadow">
                  +{Math.round((z.modifier - 1) * 100)}%
                </span>
              )}

              <div>
                <p className={`text-[11px] font-bold leading-snug mb-1 ${heat.text}`}>
                  {zone}
                </p>
                <span className={`inline-block rounded-full px-1.5 py-0.5 text-[9px] font-bold ${heat.badge}`}>
                  {z.adjusted_risk}
                </span>
              </div>

              <div className="mt-2 space-y-0.5">
                <div className="flex justify-between text-[10px]">
                  <span className="text-slate-500">Priority</span>
                  <span className={`font-bold ${heat.text}`}>{z.adjusted_priority}</span>
                </div>
                <div className="flex justify-between text-[10px]">
                  <span className="text-slate-500">Proj. Cases</span>
                  <span className="font-semibold text-slate-700">{z.adjusted_cases.toFixed(0)}</span>
                </div>
              </div>

              {/* Score bar */}
              <div className="mt-2 h-1.5 rounded-full bg-white/60 overflow-hidden">
                <div
                  className={`h-full rounded-full transition-all duration-500 ${
                    z.adjusted_priority >= 76 ? "bg-red-500" :
                    z.adjusted_priority >= 51 ? "bg-orange-500" :
                    z.adjusted_priority >= 26 ? "bg-yellow-400" : "bg-slate-400"
                  }`}
                  style={{ width: `${z.adjusted_priority}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Compass/orientation note */}
      <div className="flex items-center justify-between text-[10px] text-slate-400 mb-3">
        <span>← West · Kamrangirchar</span>
        <span>Schematic layout</span>
        <span>East · Jatrabari →</span>
      </div>

      {/* Disclaimer */}
      <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5">
        <Info className="h-3.5 w-3.5 text-amber-600 flex-shrink-0 mt-0.5" />
        <p className="text-[10px] text-amber-700 leading-relaxed">
          <span className="font-semibold">Prototype note: </span>
          Priority scores 0–100: Routine (0–25) | Moderate (26–50) | High (51–75) | Critical (76+).
          Zone positions are approximate. This schematic does not represent official ward boundaries or a validated geospatial map.
          {surgeKey !== "normal" && (
            <span className="font-semibold"> Scenario simulation is a what-if overlay and does not retrain the forecasting model.</span>
          )}
        </p>
      </div>
    </div>
  );
}
