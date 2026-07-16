"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { ZoneSurgeData } from "@/lib/surgeScenarios";

interface Props {
  zones: ZoneSurgeData[];
  isNormal: boolean;
}

// Short zone labels for x-axis
const SHORT: Record<string, string> = {
  Kamrangirchar:            "Kamrangirchar",
  "Mitford / Old Dhaka":    "Mitford",
  Dhanmondi:                "Dhanmondi",
  "Jatrabari / Sayedabad":  "Jatrabari",
  "Lalbagh / Hazaribagh":   "Lalbagh",
};

// Colour by adjusted priority
function barFill(score: number, isBaseline: boolean): string {
  if (isBaseline) return "#cbd5e1"; // slate-300 for baseline
  if (score >= 76) return "#ef4444"; // red
  if (score >= 51) return "#f97316"; // orange
  if (score >= 26) return "#eab308"; // yellow
  return "#94a3b8";
}

export default function ScenarioImpactChart({ zones, isNormal }: Props) {
  const data = zones.map((z) => ({
    name: SHORT[z.zone_name] ?? z.zone_name,
    Baseline: z.baselinePlanningPriority,
    Adjusted: isNormal ? null : z.adjustedPlanningPriority,
    adjScore: z.adjustedPlanningPriority,
  }));

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-semibold text-slate-700 mb-0.5">
        Priority Score — Before &amp; After Surge
      </p>
      <p className="text-[10px] text-slate-400 mb-4">
        {isNormal
          ? "Baseline expected-case priority scores. Select a surge scenario to see adjustment."
          : "Adjusted scores reflect the surge simulation overlay. Grey = baseline."}
      </p>

      <ResponsiveContainer width="100%" height={240}>
        <BarChart
          data={data}
          margin={{ top: 5, right: 16, left: 0, bottom: 5 }}
          barCategoryGap="30%"
          barGap={3}
        >
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis
            dataKey="name"
            tick={{ fontSize: 10, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v: number) => `${v}`}
          />
          <Tooltip
            formatter={(value, name) => [
              `${Number(value)} / 100`,
              name === "Adjusted" ? "Surge-Adjusted" : "Baseline",
            ]}
            contentStyle={{ fontSize: 11, borderRadius: 8 }}
          />
          <Legend
            wrapperStyle={{ fontSize: 11 }}
            formatter={(value: string) =>
              value === "Adjusted" ? "Surge-Adjusted" : "Baseline"
            }
          />
          {/* Critical threshold line */}
          <ReferenceLine y={76} stroke="#ef4444" strokeDasharray="4 2" strokeWidth={1}>
          </ReferenceLine>
          <ReferenceLine y={51} stroke="#f97316" strokeDasharray="4 2" strokeWidth={1}>
          </ReferenceLine>

          {/* Baseline bars always shown */}
          <Bar dataKey="Baseline" maxBarSize={32} radius={[3, 3, 0, 0]}>
            {data.map((_, i) => (
              <Cell key={i} fill="#cbd5e1" />
            ))}
          </Bar>

          {/* Adjusted bars — only when not normal */}
          {!isNormal && (
            <Bar dataKey="Adjusted" maxBarSize={32} radius={[3, 3, 0, 0]}>
              {data.map((d, i) => (
                <Cell key={i} fill={barFill(d.adjScore, false)} />
              ))}
            </Bar>
          )}
        </BarChart>
      </ResponsiveContainer>

      <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-slate-500">
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-red-400 inline-block" />
          76+ Critical
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-orange-400 inline-block" />
          51–75 High
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-yellow-400 inline-block" />
          26–50 Moderate
        </span>
        <span className="flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-slate-300 inline-block" />
          Baseline
        </span>
      </div>
    </div>
  );
}
