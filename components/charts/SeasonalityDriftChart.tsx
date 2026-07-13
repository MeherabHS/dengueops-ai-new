"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { BRAND } from "@/lib/constants";

import type { SeasonalityDriftPoint } from "@/lib/types";

interface Props {
  data: SeasonalityDriftPoint[];
}

export default function SeasonalityDriftChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="year" tick={{ fontSize: 11, fill: BRAND.slate }} />
        <YAxis yAxisId="left" tick={{ fontSize: 11, fill: BRAND.slate }} />
        <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: BRAND.slate }} domain={[38, 48]} />
        <Tooltip contentStyle={{ fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Line
          yAxisId="left"
          type="monotone"
          dataKey="peak_cases"
          name="Peak Cases"
          stroke={BRAND.alertRed}
          strokeWidth={2}
          dot={{ r: 4 }}
        />
        <Line
          yAxisId="right"
          type="monotone"
          dataKey="peak_week"
          name="Peak Epi Week"
          stroke={BRAND.cyan}
          strokeWidth={2}
          strokeDasharray="5 3"
          dot={{ r: 4 }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
