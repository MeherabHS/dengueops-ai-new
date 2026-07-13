"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  Cell,
  ResponsiveContainer,
} from "recharts";
import chartDataRaw from "@/data/chart_data.json";
import { BRAND, CHART_COLORS } from "@/lib/constants";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const cd = chartDataRaw as any;

interface ErrorBar {
  model: string;
  mae: number;
  rmse: number;
}

const SHORT_NAMES: Record<string, string> = {
  "Naive Baseline": "Naive",
  "Moving Average Baseline (4-week)": "Mov. Avg.",
  "Gradient Boosting Regressor (scikit-learn)": "Historical GBR",
};

const MAE_COLORS  = [CHART_COLORS.muted, BRAND.alertOrange, CHART_COLORS.forecast];
const RMSE_COLORS = [CHART_COLORS.observed, BRAND.alertYellow, BRAND.cyanLight];

export default function ErrorComparisonPanel() {
  const raw: ErrorBar[] = cd?.model_error_bars ?? [];

  if (!raw.length) {
    return (
      <div className="flex items-center justify-center h-40 rounded-xl border border-dashed border-slate-300 bg-slate-50">
        <p className="text-xs text-slate-400">
          Error comparison data will appear after running the analytics pipeline.
        </p>
      </div>
    );
  }

  const data = raw.map((r) => ({
    ...r,
    shortModel: SHORT_NAMES[r.model] ?? r.model,
  }));

  return (
    <section id="error-chart" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Error Analysis
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-1">
        Forecast Error by Model
      </h2>
      <p className="text-sm text-slate-500 mb-6 italic">&ldquo;Lower is better.&rdquo;</p>
      <p className="text-xs text-slate-500 mb-4">Primary metrics aggregate all rolling-origin folds; active uncertainty uses RF rolling residuals, while the legacy holdout RMSE remains planning compatibility only.</p>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">

        {/* MAE chart */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold text-slate-600 mb-1">MAE by Model</p>
          <p className="text-[10px] text-slate-400 mb-4">Mean Absolute Error — lower is better</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="shortModel" tick={{ fontSize: 11, fill: CHART_COLORS.muted }} />
              <YAxis tick={{ fontSize: 11, fill: CHART_COLORS.muted }} />
              <Tooltip
                formatter={(v) => [Number(v).toFixed(1), "MAE"]}
                contentStyle={{ fontSize: 12 }}
              />
              <Bar dataKey="mae" name="MAE" maxBarSize={60} radius={[4, 4, 0, 0]}>
                {data.map((_, i) => (
                  <Cell key={i} fill={MAE_COLORS[i % MAE_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* RMSE chart */}
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <p className="text-xs font-semibold text-slate-600 mb-1">RMSE by Model</p>
          <p className="text-[10px] text-slate-400 mb-4">Root Mean Squared Error — penalizes large errors</p>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={CHART_COLORS.grid} />
              <XAxis dataKey="shortModel" tick={{ fontSize: 11, fill: CHART_COLORS.muted }} />
              <YAxis tick={{ fontSize: 11, fill: CHART_COLORS.muted }} />
              <Tooltip
                formatter={(v) => [Number(v).toFixed(1), "RMSE"]}
                contentStyle={{ fontSize: 12 }}
              />
              <Bar dataKey="rmse" name="RMSE" maxBarSize={60} radius={[4, 4, 0, 0]}>
                {data.map((_, i) => (
                  <Cell key={i} fill={RMSE_COLORS[i % RMSE_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Model comparison legend */}
      <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 text-xs">
          {data.map((d, i) => (
            <div key={d.shortModel} className="flex items-center justify-between border-r border-slate-100 last:border-0 pr-4 last:pr-0">
              <div className="flex items-center gap-2">
                <span className="h-3 w-3 rounded-sm flex-shrink-0" style={{ background: MAE_COLORS[i] }} />
                <span className="font-medium text-slate-700">{d.shortModel}</span>
              </div>
              <span className="font-mono text-slate-500">
                MAE {d.mae.toFixed(1)} · RMSE {d.rmse.toFixed(1)}
              </span>
            </div>
          ))}
        </div>
      </div>

      <p className="text-[10px] text-slate-400 mt-2 text-right">
        Source: <code className="font-mono">data/chart_data.json · model_error_bars</code>
      </p>
    </section>
  );
}
