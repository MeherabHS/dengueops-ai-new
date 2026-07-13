"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  LineChart,
  Line,
  ResponsiveContainer,
} from "recharts";
import { Trophy, Info } from "lucide-react";
import validationDataRaw from "@/data/validation_metrics.json";
import { BRAND } from "@/lib/constants";

// ── Types for Phase 3 validation_metrics.json ─────────────────────────────

interface ModelMetrics {
  mae: number;
  rmse: number;
  mape: number;
}

interface AVPRow {
  epi_year: number;
  epi_week: number;
  actual: number;
  naive_pred: number;
  moving_average_pred: number;
  ml_pred: number;
}

interface PeriodInfo {
  epi_year_start: number;
  epi_week_start: number;
  epi_year_end: number;
  epi_week_end: number;
}

interface Phase3ValidationData {
  target: string;
  validation_design: string;
  train_rows: number;
  test_rows: number;
  train_period: PeriodInfo;
  test_period: PeriodInfo;
  metrics: {
    naive: ModelMetrics;
    moving_average: ModelMetrics;
    gradient_boosting: ModelMetrics;
  };
  best_model: string;
  feature_count: number;
  features_used: string[];
  actual_vs_predicted: AVPRow[];
  notes: string[];
}

const vm = validationDataRaw as Phase3ValidationData;

// ── Display helpers ───────────────────────────────────────────────────────

const MODEL_DISPLAY: Record<string, { label: string; role: string; color: string }> = {
  naive:              { label: "Naive (Last Known)",    role: "Baseline",   color: "#94a3b8" },
  moving_average:     { label: "Moving Average (4w)",   role: "Baseline",   color: "#64748b" },
  gradient_boosting:  { label: "GradientBoostingRegressor", role: "Historical P1.1 ML", color: BRAND.cyan },
};

function periodLabel(p: PeriodInfo) {
  return `${p.epi_year_start} W${p.epi_week_start} → ${p.epi_year_end} W${p.epi_week_end}`;
}

/** Create a short x-axis label from year/week: "25W50", "26W01" */
function weekLabel(row: AVPRow) {
  const yr = String(row.epi_year).slice(-2);
  const wk = String(row.epi_week).padStart(2, "0");
  return `${yr}W${wk}`;
}

// ── Bar chart data ────────────────────────────────────────────────────────

const barData = (["naive", "moving_average", "gradient_boosting"] as const).map(
  (key) => ({
    model: MODEL_DISPLAY[key].label,
    shortName: key === "gradient_boosting" ? "GBR" : key === "moving_average" ? "Mov.Avg" : "Naive",
    MAE: vm.metrics[key].mae,
    RMSE: vm.metrics[key].rmse,
    color: MODEL_DISPLAY[key].color,
  })
);

// ── Line chart data ────────────────────────────────────────────────────────

const lineData = vm.actual_vs_predicted.map((row) => ({
  label: weekLabel(row),
  actual: row.actual,
  naive: row.naive_pred,
  moving_avg: row.moving_average_pred,
  gbr: row.ml_pred,
}));

// ── Main component ────────────────────────────────────────────────────────

interface Props {
  /** When false, hides the actual vs predicted chart (compact mode for dashboard) */
  showAvpChart?: boolean;
}

export default function ModelEvaluationPanel({ showAvpChart = true }: Props) {
  return (
    <div className="space-y-6">

      {/* ── Selection rationale ────────────────────────────────────────── */}
      <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 flex items-start gap-3">
        <Info className="h-4 w-4 text-sky-600 flex-shrink-0 mt-0.5" />
        <p className="text-xs text-sky-800 leading-relaxed">
          <span className="font-semibold">Model selection rationale: </span>
          This historical holdout records GradientBoostingRegressor because it achieved the lowest
          MAE ({vm.metrics.gradient_boosting.mae.toFixed(1)}) and RMSE (
          {vm.metrics.gradient_boosting.rmse.toFixed(1)}) under chronological
          time-based validation. The model is not claimed as novel; it is used as
          a practical tabular forecasting method appropriate for the feature matrix
          produced by the lag-aware feature engineering pipeline.
        </p>
      </div>

      {/* ── Split metadata ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          { label: "Validation Design",  value: "Time-based holdout" },
          { label: "Train Rows",         value: `${vm.train_rows} weeks` },
          { label: "Test Rows",          value: `${vm.test_rows} weeks` },
          { label: "Target",             value: "Cases +14 days" },
        ].map((item) => (
          <div key={item.label} className="rounded-lg border border-slate-200 bg-white p-3">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
              {item.label}
            </p>
            <p className="text-sm font-semibold text-slate-800 mt-0.5">{item.value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-xs">
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Train Period</p>
          <p className="text-sm font-medium text-slate-700 mt-0.5">{periodLabel(vm.train_period)}</p>
        </div>
        <div className="rounded-lg border border-slate-200 bg-white p-3">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">Test Period</p>
          <p className="text-sm font-medium text-slate-700 mt-0.5">{periodLabel(vm.test_period)}</p>
        </div>
      </div>

      {/* ── Model comparison table ─────────────────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-2">
          Model Comparison — Chronological Test Period
        </h3>
        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                {["Model", "MAE", "RMSE", "MAPE (%)", "Role", ""].map((h) => (
                  <th
                    key={h}
                    className="px-4 py-2.5 text-left font-semibold text-slate-600 uppercase tracking-wider text-[10px]"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {(["naive", "moving_average", "gradient_boosting"] as const).map((key) => {
                const m = vm.metrics[key];
                const d = MODEL_DISPLAY[key];
                const isBest = key === vm.best_model;
                return (
                  <tr key={key} className={isBest ? "bg-sky-50" : ""}>
                    <td className="px-4 py-2.5 font-medium text-slate-800">
                      {d.label}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {m.mae.toFixed(1)}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {m.rmse.toFixed(1)}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-700">
                      {m.mape.toFixed(1)}%
                    </td>
                    <td className="px-4 py-2.5">
                      <span
                        className={
                          d.role === "Primary ML"
                            ? "rounded-full bg-sky-100 text-sky-700 px-2 py-0.5 text-[10px] font-medium"
                            : "rounded-full bg-slate-100 text-slate-600 px-2 py-0.5 text-[10px] font-medium"
                        }
                      >
                        {d.role}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      {isBest && (
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                          <Trophy className="h-3 w-3" />
                          Best
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Bar chart: MAE & RMSE comparison ──────────────────────────── */}
      <div>
        <h3 className="text-sm font-semibold text-slate-700 mb-1">
          MAE & RMSE by Model
        </h3>
        <p className="text-[11px] text-slate-400 mb-3">
          Historical GBR achieves {Math.round((1 - vm.metrics.gradient_boosting.mae / vm.metrics.naive.mae) * 100)}%
          lower MAE than the naive baseline under chronological holdout.
        </p>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={barData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis
                dataKey="shortName"
                tick={{ fontSize: 11, fill: BRAND.slate }}
              />
              <YAxis tick={{ fontSize: 11, fill: BRAND.slate }} />
              <Tooltip
                contentStyle={{ fontSize: 11 }}
                formatter={(value) => [Number(value).toFixed(1), ""]}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="MAE" fill={BRAND.navyMid} radius={[3, 3, 0, 0]} />
              <Bar dataKey="RMSE" fill={BRAND.cyan} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* ── Actual vs predicted chart ──────────────────────────────────── */}
      {showAvpChart && (
        <div>
          <h3 className="text-sm font-semibold text-slate-700 mb-1">
            Actual vs Predicted — Test Period ({vm.test_rows} weeks)
          </h3>
          <p className="text-[11px] text-slate-400 mb-3">
            Test period: {periodLabel(vm.test_period)}. Note rapid post-peak decline
            at 2025 W51–52 — naive baseline fails to track this; GBR recovers faster.
          </p>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={lineData} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis
                  dataKey="label"
                  tick={{ fontSize: 9, fill: BRAND.slate }}
                  interval={3}
                  angle={-35}
                  textAnchor="end"
                  height={40}
                />
                <YAxis tick={{ fontSize: 11, fill: BRAND.slate }} />
              <Tooltip
                contentStyle={{ fontSize: 11 }}
                formatter={(value) => [Math.round(Number(value)).toLocaleString(), ""]}
                labelFormatter={(label) => `Week ${label}`}
              />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line
                  type="monotone"
                  dataKey="actual"
                  name="Actual"
                  stroke={BRAND.navy}
                  strokeWidth={2.5}
                  dot={{ r: 2.5 }}
                />
                <Line
                  type="monotone"
                  dataKey="gbr"
                  name="GBR Predicted"
                  stroke={BRAND.cyan}
                  strokeWidth={2}
                  strokeDasharray="5 3"
                  dot={{ r: 2 }}
                />
                <Line
                  type="monotone"
                  dataKey="naive"
                  name="Naive"
                  stroke="#94a3b8"
                  strokeWidth={1}
                  strokeDasharray="3 3"
                  dot={false}
                />
                <Line
                  type="monotone"
                  dataKey="moving_avg"
                  name="Moving Avg"
                  stroke="#cbd5e1"
                  strokeWidth={1}
                  strokeDasharray="2 4"
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* ── Validation methodology note ────────────────────────────────── */}
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 space-y-1.5">
        <p className="font-semibold">Validation methodology notes:</p>
        <ul className="list-disc list-inside space-y-1">
          <li>
            Validation uses a time-based holdout — not random row splitting.
            Every test prediction is made using only data available before that
            week in real operational time.
          </li>
          <li>
            Baselines are included to test whether the ML model adds value beyond
            simple trend continuation. A model that cannot beat the naive baseline
            provides no operational signal.
          </li>
          <li>
            Results are based on controlled synthetic/demo Dhaka South aggregate data
            (2024–2026, up to week 24) generated by the DengueOps AI data pipeline.
            Spatial allocation and facility layers are also synthetic. Optional OpenDengue
            and NASA POWER integration is available via CLI flags for future validation.
          </li>
          <li>
            Real deployment would require multi-year validated DGHS/IEDCR
            surveillance data with sub-national resolution.
          </li>
        </ul>
      </div>
    </div>
  );
}
