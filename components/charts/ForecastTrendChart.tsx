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
import { BRAND } from "@/lib/constants";

interface TrendPoint {
  week: string;
  cases: number;
  lower: number;
  upper: number;
  type: "historical" | "forecast";
}

interface Props {
  data: TrendPoint[];
}

export default function ForecastTrendChart({ data }: Props) {
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis dataKey="week" tick={{ fontSize: 10, fill: BRAND.slate }} />
        <YAxis tick={{ fontSize: 11, fill: BRAND.slate }} />
        <Tooltip contentStyle={{ fontSize: 12 }} />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <Area
          type="monotone"
          dataKey="upper"
          name="Upper CI"
          fill={BRAND.cyanLight}
          stroke="none"
          fillOpacity={0.2}
        />
        <Area
          type="monotone"
          dataKey="lower"
          name="Lower CI"
          fill={BRAND.white}
          stroke="none"
          fillOpacity={1}
        />
        <Line
          type="monotone"
          dataKey="cases"
          name="Cases"
          stroke={BRAND.navy}
          strokeWidth={2}
          dot={{ r: 2 }}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
