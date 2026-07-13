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
  ErrorBar,
  ReferenceLine,
} from "recharts";
import type { FeatureDiagnosticRecord } from "@/lib/types";
import { BRAND } from "@/lib/constants";

interface Props {
  data: FeatureDiagnosticRecord[];
}

export default function FeatureImportanceChart({ data }: Props) {
  const sorted = [...data].sort(
    (a, b) => a.rank_by_permutation - b.rank_by_permutation
  );
  const bounds = sorted.flatMap((item) => [
    item.permutation_mean - item.permutation_standard_deviation,
    item.permutation_mean + item.permutation_standard_deviation,
  ]);
  const minimum = Math.min(0, ...bounds);
  const maximum = Math.max(0, ...bounds);
  const span = Math.max(maximum - minimum, 1);
  const domain: [number, number] = [minimum - span * 0.05, maximum + span * 0.05];

  return (
    <ResponsiveContainer width="100%" height={520}>
      <BarChart
        layout="vertical"
        data={sorted}
        margin={{ top: 5, right: 30, left: 16, bottom: 5 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
        <XAxis
          type="number"
          domain={domain}
          tickFormatter={(value) => Number(value).toFixed(1)}
          tick={{ fontSize: 11, fill: BRAND.slate }}
          label={{ value: "Holdout MAE increase after permutation (cases)", position: "insideBottom", offset: -2, fontSize: 10 }}
        />
        <YAxis
          type="category"
          dataKey="feature_name"
          width={150}
          tick={{ fontSize: 10, fill: BRAND.slate }}
        />
        <ReferenceLine x={0} stroke="#475569" strokeWidth={1.5} />
        <Tooltip
          contentStyle={{ fontSize: 11 }}
          formatter={(value, name, item) => {
            const record = item.payload as FeatureDiagnosticRecord;
            if (name === "Holdout permutation mean") {
              return [
                `${Number(value).toFixed(3)} cases (SD ${record.permutation_standard_deviation.toFixed(3)})`,
                name,
              ];
            }
            return [Number(value).toFixed(4), name];
          }}
        />
        <Bar
          dataKey="permutation_mean"
          name="Holdout permutation mean"
          radius={[0, 4, 4, 0]}
        >
          <ErrorBar
            dataKey="permutation_standard_deviation"
            direction="x"
            width={4}
            stroke="#334155"
          />
          {sorted.map((item) => (
            <Cell
              key={item.feature_name}
              fill={item.permutation_is_negative ? "#f59e0b" : item.rank_by_permutation === 1 ? BRAND.navyMid : BRAND.cyan}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
