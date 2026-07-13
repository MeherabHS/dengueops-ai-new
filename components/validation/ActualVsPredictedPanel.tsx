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
import chartDataRaw from "@/data/chart_data.json";
import { BRAND, CHART_COLORS } from "@/lib/constants";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const cd = chartDataRaw as any;

interface AVPPoint {
  label: string;
  actual: number;
  naive: number;
  moving_average: number;
  gradient_boosting: number;
}

const LINES = [
  { key: "actual",            name: "Actual",                       stroke: CHART_COLORS.observed, strokeWidth: 2.5, dash: undefined },
  { key: "gradient_boosting", name: "Historical Gradient Boosting", stroke: CHART_COLORS.forecast, strokeWidth: 2, dash: "5 3" },
  { key: "naive",             name: "Naive Baseline",               stroke: CHART_COLORS.muted, strokeWidth: 1.5, dash: "3 3" },
  { key: "moving_average",    name: "Moving Average",               stroke: BRAND.alertOrange, strokeWidth: 1.5, dash: "6 2" },
];

export default function ActualVsPredictedPanel() {
  const raw: AVPPoint[] = cd?.actual_vs_predicted ?? [];

  if (!raw.length) {
    return (
      <div className="flex items-center justify-center h-48 rounded-xl border border-dashed border-slate-300 bg-slate-50">
        <p className="text-xs text-slate-400">
          Actual vs predicted data will appear after running the analytics pipeline.
        </p>
      </div>
    );
  }

  return (
    <section id="avp-chart" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Forecast Quality
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-1">
        Actual vs Predicted Dengue Cases
      </h2>
      <p className="text-sm text-slate-500 mb-6 italic">
        &ldquo;One unseen two-week-ahead target at each rolling forecast origin.&rdquo;
      </p>

      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <p className="text-xs font-semibold text-slate-500 mb-4 uppercase tracking-wider">
          Rolling Origins · {raw.length} folds
        </p>

        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={raw} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
            <XAxis
              dataKey="label"
              tick={{ fontSize: 10, fill: CHART_COLORS.muted }}
              tickFormatter={(v: string) => {
                const parts = v.split("-");
                return parts[1] ?? v;
              }}
              angle={-35}
              textAnchor="end"
              height={52}
              interval={2}
            />
            <YAxis
              tick={{ fontSize: 11, fill: CHART_COLORS.muted }}
              tickFormatter={(v: number) => v.toLocaleString()}
            />
            <Tooltip
              formatter={(value) => [Number(value).toLocaleString(), ""]}
              labelFormatter={(label) => `Epi Week: ${label}`}
              contentStyle={{ fontSize: 12 }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {LINES.map((l) => (
              <Line
                key={l.key}
                type="monotone"
                dataKey={l.key}
                name={l.name}
                stroke={l.stroke}
                strokeWidth={l.strokeWidth}
                strokeDasharray={l.dash}
                dot={l.key === "actual" ? { r: 3 } : false}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>

        <p className="text-[10px] text-slate-400 mt-3 text-right">
          Source: <code className="font-mono">data/chart_data.json · actual_vs_predicted</code>
        </p>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4 text-center">
        {LINES.map((l) => (
          <div key={l.key} className="flex items-center gap-2 justify-center rounded-lg border border-slate-100 bg-white px-3 py-2 shadow-sm">
            <span
              className="inline-block h-2.5 w-5 rounded-sm flex-shrink-0"
              style={{ background: l.stroke }}
            />
            <span className="text-[11px] font-medium text-slate-600">{l.name}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
