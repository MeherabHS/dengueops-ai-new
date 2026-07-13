import { CheckCircle2, Clock, FileJson, Activity, AlertTriangle, Database } from "lucide-react";
import { pipelineRunSummary } from "@/lib/demo-data";
import { formatDate } from "@/lib/formatters";

const STEP_LABELS: Record<string, string> = {
  feature_engineering:   "Feature Engineering (lag features, rolling stats)",
  validation_backtest:   "Temporal Backtest (chronological holdout)",
  forecast_model:        "Forecast Model (RandomForestRegressor, 14d)",
  uncertainty_engine:    "P1.3 Temporal Empirical Range Validation",
  operational_engine:    "Operational Engine (directives, SDH, bed pressure)",
  dashboard_exporter:    "Dashboard Exporter (JSON outputs for UI)",
};

function StatusBadge({ status }: { status: string }) {
  const cfg =
    status === "success"
      ? "bg-emerald-100 text-emerald-700 border-emerald-300"
      : status === "partial"
      ? "bg-yellow-100 text-yellow-700 border-yellow-300"
      : "bg-red-100 text-red-700 border-red-300";

  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${cfg}`}>
      {status === "success" && <CheckCircle2 className="h-3 w-3" />}
      {status !== "success" && <AlertTriangle className="h-3 w-3" />}
      {status}
    </span>
  );
}

/** Strip full Windows/Unix path — keep only filename */
function basename(path: string): string {
  return path.split(/[/\\]/).pop() ?? path;
}

export default function PipelineStatusPanel() {
  const ps = pipelineRunSummary;
  const fs = ps.forecast_summary;
  const ds = ps.directives_summary;
  const totalTime = Object.values(ps.step_timings_sec).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-5">

      {/* ── Run header ─────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
        <div className="flex items-center gap-2">
          <Activity className="h-5 w-5 text-sky-500" />
          <div>
            <p className="text-sm font-bold text-slate-800">Pipeline Run</p>
            <p className="text-xs text-slate-400">{formatDate(ps.run_timestamp)} · {ps.run_timestamp.split("T")[1]?.slice(0, 8)} UTC</p>
          </div>
        </div>
        <StatusBadge status={ps.status} />
        <div className="ml-auto text-right">
          <p className="text-xs text-slate-500">
            {ps.completed_steps.length} steps · {totalTime.toFixed(1)}s total
          </p>
        </div>
      </div>

      {/* ── Step timings ────────────────────────────────────────────────── */}
      <div>
        <p className="text-sm font-semibold text-slate-700 mb-2">Pipeline Steps</p>
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
          <table className="min-w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-200">
              <tr>
                <th className="px-4 py-2.5 text-left font-semibold text-slate-500 uppercase tracking-wider text-[10px]">Step</th>
                <th className="px-4 py-2.5 text-right font-semibold text-slate-500 uppercase tracking-wider text-[10px]">Time (s)</th>
                <th className="px-4 py-2.5 text-center font-semibold text-slate-500 uppercase tracking-wider text-[10px]">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {ps.completed_steps.map((step) => (
                <tr key={step} className="hover:bg-slate-50">
                  <td className="px-4 py-2.5 text-slate-700 font-medium">
                    {STEP_LABELS[step] ?? step}
                  </td>
                  <td className="px-4 py-2.5 text-right font-mono text-slate-600">
                    {ps.step_timings_sec[step]?.toFixed(2) ?? "—"}s
                  </td>
                  <td className="px-4 py-2.5 text-center">
                    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
                      <CheckCircle2 className="h-3 w-3" />
                      OK
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Forecast + directives summary ───────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">

        <div className="rounded-xl border border-sky-200 bg-sky-50 p-4 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <Activity className="h-4 w-4 text-sky-600" />
            <p className="text-xs font-semibold text-sky-700 uppercase tracking-wider">Forecast Summary</p>
          </div>
          <div className="space-y-1.5 text-xs text-slate-700">
            <div className="flex justify-between">
              <span className="text-slate-500">Cases (expected)</span>
              <span className="font-bold text-slate-900">{fs.expected_case.toLocaleString()}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Planning Low / High</span>
              <span className="font-mono">{fs.best_case} / {fs.worst_case}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Growth Factor</span>
              <span className="font-bold">{fs.growth_factor.toFixed(3)}×</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Risk Level</span>
              <span className={`font-semibold ${
                fs.risk_level === "Critical" ? "text-red-700" :
                fs.risk_level === "High" ? "text-orange-700" :
                fs.risk_level === "Moderate" ? "text-yellow-700" : "text-emerald-700"
              }`}>{fs.risk_level} ({fs.risk_score}/100)</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Target</span>
              <span className="font-mono">{fs.target_epi_year} W{fs.target_epi_week}</span>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-indigo-200 bg-indigo-50 p-4 shadow-sm">
          <div className="flex items-center gap-2 mb-3">
            <Database className="h-4 w-4 text-indigo-600" />
            <p className="text-xs font-semibold text-indigo-700 uppercase tracking-wider">Directives Summary</p>
          </div>
          <div className="space-y-1.5 text-xs text-slate-700">
            <div className="flex justify-between">
              <span className="text-slate-500">Total Facilities</span>
              <span className="font-bold text-slate-900">{ds.total_facilities}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Public Anchors</span>
              <span className="font-mono">{ds.total_public_government_anchors}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Facilities — Bed Gap</span>
              <span className={`font-bold ${ds.facilities_with_expected_bed_gap > 0 ? "text-orange-700" : "text-emerald-700"}`}>
                {ds.facilities_with_expected_bed_gap} / {ds.total_facilities}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Critical Supply Alerts</span>
              <span className={`font-bold ${ds.critical_supply_alerts > 0 ? "text-red-700" : "text-emerald-700"}`}>
                {ds.critical_supply_alerts}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Total Recommendations</span>
              <span className="font-mono">{ds.total_recommendations}</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Generated files ──────────────────────────────────────────────── */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <FileJson className="h-4 w-4 text-slate-500" />
          <p className="text-sm font-semibold text-slate-700">Generated Files</p>
        </div>
        <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
          {ps.generated_files.map((file) => (
            <div
              key={file}
              className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
            >
              <FileJson className="h-3.5 w-3.5 text-sky-500 flex-shrink-0" />
              <span className="text-xs font-mono text-slate-600 truncate">
                {basename(file)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Pipeline architecture note ────────────────────────────────── */}
      <div className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-600 leading-relaxed">
        <p className="font-semibold text-slate-700 mb-1">Pipeline Architecture</p>
        <p>
          The analytics pipeline runs as a sequence of Python scripts orchestrated by{" "}
          <code className="font-mono text-sky-700 bg-sky-100 px-1 rounded">
            analytics/run_pipeline.py
          </code>.
          Each step reads from upstream outputs and writes structured JSON to{" "}
          <code className="font-mono text-sky-700 bg-sky-100 px-1 rounded">data/</code>.
          The Next.js dashboard imports these files at build time and serves them as static data.
          No backend database or live surveillance feed is required.
        </p>
        <p className="mt-1.5 text-slate-500">
          <span className="font-medium text-slate-600">Run command:</span>{" "}
          <code className="font-mono bg-slate-200 px-1 rounded">python analytics/run_pipeline.py</code>
          {" → "}<code className="font-mono bg-slate-200 px-1 rounded">npm run dev</code>
        </p>
      </div>

      {/* ── Timing note ─────────────────────────────────────────────────── */}
      <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs text-amber-800">
        <Clock className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
        <p>
          Pipeline Step 1 uses controlled synthetic Dhaka South demonstration data for dengue cases and climate.
          All facility and spatial layers are also synthetic. Optional experimental data pathways are available via
          <code className="mx-1 font-mono text-sky-700 bg-sky-100 px-0.5 rounded text-[10px]">--use-opendengue</code> /
          <code className="mx-1 font-mono text-sky-700 bg-sky-100 px-0.5 rounded text-[10px]">--use-nasa-power-climate</code> flags.
          Terminal output is not the evaluator-facing product — this dashboard is.
        </p>
      </div>
    </div>
  );
}
