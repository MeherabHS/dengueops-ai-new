import Link from "next/link";
import { ArrowRight, Activity, TrendingUp, MapPin, Building2, AlertTriangle, BedDouble } from "lucide-react";
// Import directly — server component, no need to go through lib/demo-data
import summaryRaw from "@/data/dashboard_summary.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const s = summaryRaw as any;
const hm = s?.headline_metrics ?? {};
const op = s?.operational_summary ?? {};

interface PreviewMetric {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  sub?: string;
  accent: string;
  iconColor: string;
}

const METRICS: PreviewMetric[] = [
  {
    icon: <Activity className="h-5 w-5" />,
    label: "Forecasted Cases",
    value: hm.forecast_cases ?? "—",
    sub: "Expected · 14-day horizon",
    accent: "border-sky-200 bg-sky-50",
    iconColor: "text-sky-600",
  },
  {
    icon: <TrendingUp className="h-5 w-5" />,
    label: "Risk Level",
    value: hm.risk_level ?? "—",
    sub: `Risk score: ${hm.risk_score ?? "—"} / 100`,
    accent:
      hm.risk_level === "High" || hm.risk_level === "Critical"
        ? "border-orange-200 bg-orange-50"
        : hm.risk_level === "Moderate"
        ? "border-yellow-200 bg-yellow-50"
        : "border-emerald-200 bg-emerald-50",
    iconColor:
      hm.risk_level === "High" || hm.risk_level === "Critical"
        ? "text-orange-600"
        : "text-yellow-600",
  },
  {
    icon: <MapPin className="h-5 w-5" />,
    label: "Highest Priority Zone",
    value: hm.highest_priority_zone ?? "—",
    sub: "Vulnerability-gated exposure score",
    accent: "border-indigo-200 bg-indigo-50",
    iconColor: "text-indigo-600",
  },
  {
    icon: <Building2 className="h-5 w-5" />,
    label: "Facilities Monitored",
    value: hm.total_facilities ?? "—",
    sub: `${hm.total_public_government_anchors ?? "—"} real public anchors`,
    accent: "border-slate-200 bg-slate-50",
    iconColor: "text-slate-600",
  },
  {
    icon: <AlertTriangle className="h-5 w-5" />,
    label: "Critical Supply Alerts",
    value: hm.critical_supply_alerts ?? "—",
    sub: "Items below 7-day threshold",
    accent:
      (hm.critical_supply_alerts ?? 0) > 0
        ? "border-red-200 bg-red-50"
        : "border-emerald-200 bg-emerald-50",
    iconColor:
      (hm.critical_supply_alerts ?? 0) > 0 ? "text-red-600" : "text-emerald-600",
  },
  {
    icon: <BedDouble className="h-5 w-5" />,
    label: "Facilities — Bed Gap",
    value: `${op.facilities_with_expected_bed_gap ?? "—"} / ${hm.total_facilities ?? "—"}`,
    sub: "Expected bed deficit (expected scenario)",
    accent:
      (op.facilities_with_expected_bed_gap ?? 0) > 0
        ? "border-orange-200 bg-orange-50"
        : "border-emerald-200 bg-emerald-50",
    iconColor:
      (op.facilities_with_expected_bed_gap ?? 0) > 0 ? "text-orange-600" : "text-emerald-600",
  },
];

export default function PrototypePreviewSection() {
  return (
    <section className="bg-slate-50 border-y border-slate-200">
      <div className="mx-auto max-w-5xl px-4 py-16 sm:px-6 lg:px-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
          Live Prototype Preview
        </p>
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          Current Pipeline Output Snapshot
        </h2>
        <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
          Metrics below are read from the latest analytics pipeline run.
          Values use <span className="font-medium text-slate-700">synthetic demonstration data</span>.
        </p>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 mb-8">
          {METRICS.map((m) => (
            <div
              key={m.label}
              className={`rounded-xl border ${m.accent} p-4 shadow-sm`}
            >
              <div className={`mb-2 ${m.iconColor}`}>{m.icon}</div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 mb-0.5">
                {m.label}
              </p>
              <p className="text-xl font-bold text-slate-900 leading-tight mb-1">
                {m.value}
              </p>
              {m.sub && <p className="text-[10px] text-slate-400">{m.sub}</p>}
            </div>
          ))}
        </div>

        <div className="text-center">
          <p className="text-xs text-slate-400 mb-4">
            Synthetic demonstration data · Advisory outputs · Human review required
          </p>
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-6 py-3 text-sm font-semibold text-white shadow hover:bg-sky-500 transition-colors"
          >
            Open Full Dashboard <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  );
}
