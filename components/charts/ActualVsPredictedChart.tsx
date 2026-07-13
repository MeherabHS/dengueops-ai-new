"use client";

import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { ActualVsPredicted } from "@/lib/types";
import { BRAND } from "@/lib/constants";

interface Props {
  data: ActualVsPredicted[];
}

export default function ActualVsPredictedChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis
          dataKey="epi_week"
          tickFormatter={(v) => `W${v}`}
          tick={{ fontSize: 11, fill: BRAND.slate }}
          label={{ value: "Epi Week", position: "insideBottomRight", offset: -8, fontSize: 11 }}
        />
        <YAxis tick={{ fontSize: 11, fill: BRAND.slate }} />
        <Tooltip
          formatter={(value) => [Number(value).toLocaleString(), ""]}
          labelFormatter={(label) => `Epi Week ${label}`}
          contentStyle={{ fontSize: 12 }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Area
          type="monotone"
          dataKey="upper_bound"
          name="Upper Bound"
          fill={BRAND.cyanLight}
          stroke="none"
          fillOpacity={0.25}
        />
        <Area
          type="monotone"
          dataKey="lower_bound"
          name="Lower Bound"
          fill={BRAND.white}
          stroke="none"
          fillOpacity={1}
        />
        <Line
          type="monotone"
          dataKey="actual"
          name="Actual Cases"
          stroke={BRAND.navy}
          strokeWidth={2}
          dot={{ r: 3 }}
        />
        <Line
          type="monotone"
          dataKey="predicted"
          name="Predicted Cases"
          stroke={BRAND.cyan}
          strokeWidth={2}
          strokeDasharray="5 3"
          dot={{ r: 3 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
