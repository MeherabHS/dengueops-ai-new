"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { Directive } from "@/lib/types";
import { BRAND } from "@/lib/constants";

interface Props {
  directives: Directive[];
}

/** Unique short label using facility_id to avoid duplicates across zones. */
function shortLabel(name: string, id: string): string {
  return name.length <= 16 ? name : `${name.split(" ")[0]} (${id})`;
}

export default function BedGapChart({ directives }: Props) {
  // bed_gap_expected is POSITIVE when there is a deficit
  const data = directives.map((d) => ({
    facilityId: d.facility_id,          // unique key for XAxis dataKey
    label: shortLabel(d.facility_name, d.facility_id),
    bed_gap: d.bed_gap_expected,
  }));

  return (
    <ResponsiveContainer width="100%" height={280}>
      <BarChart data={data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis
          dataKey="facilityId"
          tickFormatter={(id: string) => data.find((d) => d.facilityId === id)?.label ?? id}
          tick={{ fontSize: 9, fill: BRAND.slate }}
          interval={0}
          angle={-25}
          textAnchor="end"
          height={50}
        />
        <YAxis
          tick={{ fontSize: 11, fill: BRAND.slate }}
          label={{ value: "Bed Deficit", angle: -90, position: "insideLeft", offset: 10, fontSize: 11 }}
        />
        <Tooltip
          formatter={(v) => [`${v} beds`, "Projected bed deficit (expected scenario)"]}
          contentStyle={{ fontSize: 12 }}
        />
        <ReferenceLine y={0} stroke={BRAND.slate} strokeWidth={1.5} />
        <Bar dataKey="bed_gap" name="Bed Deficit (Expected)" radius={[4, 4, 0, 0]}>
          {data.map((d, i) => (
            <Cell
              key={i}
              fill={d.bed_gap > 5 ? BRAND.alertRed : d.bed_gap > 0 ? BRAND.alertOrange : BRAND.success}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
