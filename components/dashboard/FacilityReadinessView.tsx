import { Building2, AlertCircle, AlertTriangle, CheckCircle2, BedDouble, Package } from "lucide-react";
import SectionHeader from "@/components/ui/SectionHeader";
import FacilityReadinessTable from "@/components/dashboard/FacilityReadinessTable";
import SupplyDepletionChart from "@/components/charts/SupplyDepletionChart";
import BedGapChart from "@/components/charts/BedGapChart";
import StatusPill from "@/components/ui/StatusPill";
import type { Directive } from "@/lib/types";
import { getSdhSeverity } from "@/lib/risk-utils";

interface Props {
  directives: Directive[];
}

export default function FacilityReadinessView({ directives }: Props) {
  const allAlerts = directives.flatMap((d) =>
    d.inventory_alerts.map((a) => ({ ...a, zone_name: d.zone_name, facility_name: d.facility_name }))
  );
  const criticalAlerts = allAlerts.filter((a) => a.alert_level === "Critical");
  const warningAlerts = allAlerts.filter((a) => a.alert_level === "Warning");

  // bed_gap_expected is POSITIVE when a deficit exists
  const bedGapFacilities = directives.filter((d) => d.bed_gap_expected > 0);

  return (
    <div className="space-y-8">

      {/* ── Audience badge ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2">
        <Building2 className="h-4 w-4 text-slate-500 flex-shrink-0" />
        <p className="text-xs text-slate-600">
          <span className="font-semibold text-slate-700">Audience:</span>{" "}
          Hospital administrators, diagnostic centre managers, and facility supply
          chain coordinators. This view focuses on physical resource readiness —
          bed capacity, NS1/RDT kit stock, and IV fluid depletion horizons.
        </p>
      </div>

      {/* ── Status summary row ───────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Facilities Tracked
          </p>
          <p className="text-2xl font-extrabold text-slate-900 mt-1">
            {directives.length}
          </p>
        </div>
        <div className={`rounded-xl border p-3 shadow-sm ${bedGapFacilities.length > 0 ? "border-orange-200 bg-orange-50" : "border-emerald-200 bg-emerald-50"}`}>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Bed Deficit Facilities
          </p>
          <p className={`text-2xl font-extrabold mt-1 ${bedGapFacilities.length > 0 ? "text-orange-700" : "text-emerald-700"}`}>
            {bedGapFacilities.length}
            <span className="text-sm font-normal text-slate-500 ml-1">/ {directives.length}</span>
          </p>
        </div>
        <div className={`rounded-xl border p-3 shadow-sm ${criticalAlerts.length > 0 ? "border-red-200 bg-red-50" : "border-emerald-200 bg-emerald-50"}`}>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Critical Supply Alerts
          </p>
          <p className={`text-2xl font-extrabold mt-1 ${criticalAlerts.length > 0 ? "text-red-700" : "text-emerald-700"}`}>
            {criticalAlerts.length}
          </p>
        </div>
        <div className={`rounded-xl border p-3 shadow-sm ${warningAlerts.length > 0 ? "border-amber-200 bg-amber-50" : "border-slate-200 bg-white"}`}>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Supply Warnings
          </p>
          <p className={`text-2xl font-extrabold mt-1 ${warningAlerts.length > 0 ? "text-amber-700" : "text-slate-900"}`}>
            {warningAlerts.length}
          </p>
        </div>
      </div>

      {/* ── Bed deficit warning card ─────────────────────────────────── */}
      {bedGapFacilities.length > 0 && (
        <div className="flex items-start gap-3 rounded-lg border border-orange-200 bg-orange-50 px-4 py-3">
          <AlertTriangle className="h-5 w-5 text-orange-500 flex-shrink-0 mt-0.5" />
          <p className="text-sm text-orange-800">
            <span className="font-semibold">
              {bedGapFacilities.length} of {directives.length} facilities
            </span>{" "}
            project a bed deficit under the expected scenario. Review staffing
            and inter-facility transfer plans before the surge period.
          </p>
        </div>
      )}

      {/* ── Data credibility note ────────────────────────────────────── */}
      <div className="rounded-lg border border-sky-200 bg-sky-50 px-4 py-3 text-xs text-sky-800 leading-relaxed">
        <span className="font-semibold block mb-0.5">Data credibility note</span>
        Facility names and general bed-capacity figures are based on public/government
        references where available. Dengue-specific bed allocation, current occupancy,
        NS1/RDT stock, IV fluid stock, and consumption values are{" "}
        <span className="font-semibold">synthetic demonstration values</span> — they do
        not represent actual facility records or current operational status.
      </div>

      {/* ── Facility Readiness & Bed Pressure table ──────────────────── */}
      <div>
        <SectionHeader
          title="Facility Readiness & Bed Pressure"
          subtitle="One row per facility. Real public anchor names with public reference bed capacity; dengue demo beds and SDH values are synthetic."
        />
        <FacilityReadinessTable directives={directives} />
      </div>

      {/* ── Supply & bed charts ──────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Supply Depletion & Bed Gap Charts"
          subtitle="NS1/RDT kit and IV fluid stock depletion horizons, and projected bed gaps by facility."
        />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <Package className="h-4 w-4 text-sky-600" />
              Supply Depletion Horizon (SDH)
            </p>
            <SupplyDepletionChart directives={directives} />
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-sm font-semibold text-slate-700 mb-3 flex items-center gap-2">
              <BedDouble className="h-4 w-4 text-sky-600" />
              Projected Bed Gap by Facility
            </p>
            <BedGapChart directives={directives} />
          </div>
        </div>
      </div>

      {/* ── Inventory alerts ─────────────────────────────────────────── */}
      {allAlerts.length > 0 && (
        <div>
          <SectionHeader
            title="Active Inventory Alerts"
            subtitle="Items requiring attention. Thresholds: Critical ≤ 7 days, Warning ≤ 14 days."
          />
          <div className="space-y-2">
            {allAlerts.map((alert, i) => (
              <div
                key={i}
                className={`flex items-start gap-3 rounded-lg border px-4 py-3 text-sm ${
                  alert.alert_level === "Critical"
                    ? "border-red-200 bg-red-50"
                    : "border-amber-200 bg-amber-50"
                }`}
              >
                {alert.alert_level === "Critical" ? (
                  <AlertCircle className="h-4 w-4 text-red-600 flex-shrink-0 mt-0.5" />
                ) : (
                  <AlertTriangle className="h-4 w-4 text-amber-500 flex-shrink-0 mt-0.5" />
                )}
                <div className="flex-1 min-w-0">
                  <span className={`font-semibold ${alert.alert_level === "Critical" ? "text-red-800" : "text-amber-800"}`}>
                    {alert.facility_name}
                  </span>
                  <span className="text-slate-400 mx-1">·</span>
                  <span className={alert.alert_level === "Critical" ? "text-red-700" : "text-amber-700"}>
                    {alert.message}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {allAlerts.length === 0 && (
        <div className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3">
          <CheckCircle2 className="h-5 w-5 text-emerald-600 flex-shrink-0" />
          <p className="text-sm text-emerald-800">
            No critical or warning inventory alerts under the expected scenario.
            Monitor closely if planning conditions move toward Planning High.
          </p>
        </div>
      )}

      {/* ── SDH detail per facility ──────────────────────────────────── */}
      <div>
        <SectionHeader
          title="SDH Detail by Facility"
          subtitle="Stock depletion horizon for NS1/RDT kits and IV fluids. SDH = current stock ÷ (baseline daily consumption × growth factor)."
        />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {directives.map((d) => {
            const ns1Exp = d.sdh_ns1_expected ?? 0;
            const ivfExp = d.sdh_iv_fluid_expected ?? 0;
            const ns1Severity = getSdhSeverity(ns1Exp);
            const ivfSeverity = getSdhSeverity(ivfExp);
            const bedDeficit = d.bed_gap_expected > 0;

            return (
              <div
                key={d.facility_id}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-3"
              >
                <div>
                  <p className="text-sm font-semibold text-slate-800 leading-tight">
                    {d.facility_name}
                  </p>
                  <p className="text-xs text-slate-500">{d.zone_name}</p>
                </div>

                <div className="space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">NS1/RDT SDH</span>
                    {ns1Exp > 0 ? (
                      <StatusPill label={`${ns1Exp.toFixed(1)}d`} variant={ns1Severity} size="sm" />
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">IV Fluid SDH</span>
                    {ivfExp > 0 ? (
                      <StatusPill label={`${ivfExp.toFixed(1)}d`} variant={ivfSeverity} size="sm" />
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Projected Beds</span>
                    <span className="font-medium text-slate-700">
                      {d.projected_bed_load_expected.toFixed(1)}/{d.dengue_bed_capacity_demo}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500">Bed Gap (Exp.)</span>
                    <StatusPill
                      label={bedDeficit ? `+${d.bed_gap_expected.toFixed(1)} deficit` : "No deficit"}
                      variant={d.bed_gap_expected > 5 ? "critical" : bedDeficit ? "warning" : "ok"}
                      size="sm"
                    />
                  </div>
                </div>

                {d.recommendations.length > 0 && (
                  <div className="pt-2 border-t border-slate-100">
                    <ul className="space-y-1">
                      {d.recommendations.slice(0, 2).map((rec, i) => (
                        <li key={i} className="text-[11px] text-slate-600 flex gap-1.5">
                          <span className="text-sky-500 font-bold shrink-0">→</span>
                          {rec}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
