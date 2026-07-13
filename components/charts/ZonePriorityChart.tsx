"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { Directive } from "@/lib/types";
import { BRAND } from "@/lib/constants";

interface Props {
  directives: Directive[];
}

/** One row per zone; all facilities in a zone share the same priority_score. */
function deduplicateByZone(directives: Directive[]): Directive[] {
  const seen = new Map<string, Directive>();
  for (const d of directives) {
    if (!seen.has(d.zone_id)) seen.set(d.zone_id, d);
  }
  return Array.from(seen.values());
}

export default function ZonePriorityChart({ directives }: Props) {
  const zoneRows = deduplicateByZone(directives);
  const sorted = [...zoneRows].sort((a, b) => b.priority_score - a.priority_score);

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart
        layout="vertical"
        data={sorted}
        margin={{ top: 5, right: 24, left: 8, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
        <XAxis
          type="number"
          domain={[0, 100]}
          tick={{ fontSize: 11, fill: BRAND.slate }}
          label={{ value: "Priority Score (0–100)", position: "insideBottomRight", offset: -6, fontSize: 11 }}
        />
        <YAxis
          type="category"
          dataKey="zone_name"
          width={160}
          tick={{ fontSize: 11, fill: BRAND.slate }}
        />
        <Tooltip
          formatter={(v) => [Number(v).toFixed(1), "Priority Score"]}
          contentStyle={{ fontSize: 12 }}
        />
        <Bar dataKey="priority_score" name="Priority Score" radius={[0, 4, 4, 0]}>
          {sorted.map((d) => (
            <Cell
              key={d.zone_id}
              fill={
                d.priority_score >= 85
                  ? BRAND.alertRed
                  : d.priority_score >= 65
                  ? BRAND.alertOrange
                  : BRAND.cyan
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
