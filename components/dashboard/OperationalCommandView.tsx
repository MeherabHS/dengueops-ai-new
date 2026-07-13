import { Shield, MapPin, TrendingUp, AlertTriangle, Activity } from "lucide-react";
import SectionHeader from "@/components/ui/SectionHeader";
import MetricCard from "@/components/ui/MetricCard";
import RiskBadge from "@/components/ui/RiskBadge";
import ScenarioSelector from "@/components/dashboard/ScenarioSelector";
import UncertaintySummary from "@/components/dashboard/UncertaintySummary";
import DirectiveTable from "@/components/dashboard/DirectiveTable";
import ZoneRiskTable from "@/components/dashboard/ZoneRiskTable";
import UncertaintyBandChart from "@/components/charts/UncertaintyBandChart";
import ZonePriorityChart from "@/components/charts/ZonePriorityChart";
import type { ForecastOutput, Directive, ScenarioKey } from "@/lib/types";
import { formatNumber, formatGrowthFactor } from "@/lib/formatters";

interface Props {
  forecast: ForecastOutput;
  directives: Directive[];
  scenario: ScenarioKey;
  onScenarioChange: (s: ScenarioKey) => void;
}

export default function OperationalCommandView({
  forecast,
  directives,
  scenario,
  onScenarioChange,
}: Props) {
  const sc = forecast.preparedness_scenarios[scenario];
  const criticalAlerts = directives.flatMap((d) =>
    d.inventory_alerts.filter((a) => a.alert_level === "Critical")
  );
  const topZone = [...directives].sort((a, b) => b.priority_score - a.priority_score)[0];
  const bedGapFacilities = directives.filter((d) => d.bed_gap_expected > 0).length;

  return (
    <div className="space-y-8">

      {/* ── Audience badge ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2">
        <Shield className="h-4 w-4 text-slate-500 flex-shrink-0" />
        <p className="text-xs text-slate-600">
          <span className="font-semibold text-slate-700">Audience:</span>{" "}
          Public health officials, DSCC city corporation vector-control teams,
          and district emergency planning coordinators.
          This view surfaces actionable surge signals and zone-level
          priorities — no model internals are shown here.
        </p>
      </div>

      {/* ── Scenario selector ────────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 flex flex-wrap items-center gap-4 shadow-sm">
        <ScenarioSelector active={scenario} onChange={onScenarioChange} />
        <span className="text-xs text-slate-400 ml-auto hidden sm:block">
          {forecast.city} · Horizon: {forecast.horizon_days} days ·
          Target: {forecast.target_epi_year} W{forecast.target_epi_week}
        </span>
      </div>

      {/* ── Key operational metrics ──────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <MetricCard
          title="Forecasted Cases"
          value={formatNumber(sc.forecast_cases)}
          subtitle={`Week ${forecast.target_epi_week}, ${forecast.target_epi_year}`}
          icon={<Activity className="h-4 w-4" />}
          variant={scenario === "worst_case" ? "critical" : scenario === "expected_case" ? "warning" : "success"}
        />
        <MetricCard
          title="Growth Factor"
          value={formatGrowthFactor(sc.growth_factor)}
          subtitle="vs 4-week rolling avg"
          icon={<TrendingUp className="h-4 w-4" />}
          variant={sc.growth_factor >= 2 ? "critical" : sc.growth_factor >= 1.5 ? "warning" : "success"}
        />
        <MetricCard
          title="Risk Level"
          value={<RiskBadge level={sc.risk_level} size="sm" />}
          subtitle={`Score: ${sc.risk_score} / 100`}
          variant={sc.risk_level === "Critical" ? "critical" : sc.risk_level === "High" ? "warning" : "default"}
        />
        <MetricCard
          title="Highest Priority Zone"
          value={topZone?.zone_name ?? "—"}
          subtitle={`Priority score: ${topZone?.priority_score.toFixed(0) ?? "—"}`}
          icon={<MapPin className="h-4 w-4" />}
          variant="info"
        />
        <MetricCard
          title="Critical Supply Alerts"
          value={criticalAlerts.length}
          subtitle="Facilities requiring reorder"
          icon={<AlertTriangle className="h-4 w-4" />}
          variant={criticalAlerts.length > 0 ? "critical" : "success"}
        />
      </div>

      {/* ── Uncertainty band ─────────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Preparedness Planning Scenarios"
          subtitle="Planning Low, Base, and High are operational compatibility inputs, separate from the empirical forecast range."
        />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <UncertaintySummary forecast={forecast} />
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-sm font-semibold text-slate-700 mb-3">
              Scenario Case Comparison
            </p>
            <UncertaintyBandChart forecast={forecast} />
          </div>
        </div>
      </div>

      {/* ── Zone priority ────────────────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Zone Priority Ranking"
          subtitle="Aggregated operational priority by Dhaka South zone. Five zones ranked by vulnerability-gated exposure score."
        />
        <div className="space-y-1.5 mb-4">
          <p className="text-xs text-slate-500 bg-slate-50 border border-slate-200 rounded-lg px-3 py-2">
            Zone-level outputs summarize area priority. Facility-level outputs show readiness for each public/synthetic facility anchor.
          </p>
          <p className="text-xs text-sky-700 bg-sky-50 border border-sky-200 rounded-lg px-3 py-2">
            <span className="font-semibold">Allocated cases</span> represent the expected 14-day zone-level distribution from the city-level forecast — not the total city forecast.
          </p>
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <ZonePriorityChart directives={directives} />
          </div>
          <ZoneRiskTable directives={directives} />
        </div>
      </div>

      {/* ── Facilities with bed gaps ─────────────────────────────────── */}
      {bedGapFacilities > 0 && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 flex items-start gap-3">
          <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
          <div className="text-sm text-amber-800">
            <span className="font-semibold">
              {bedGapFacilities} of {directives.length} facilities
            </span>{" "}
            project a bed deficit under the expected scenario.
            Referral protocols or temporary bed activation may be required.
          </div>
        </div>
      )}

      {/* ── Operational directives ───────────────────────────────────── */}
      <div>
        <SectionHeader
          title="Operational Directives"
          subtitle="Zone and facility-level preparedness actions ordered by priority score. All directives are advisory — review by qualified professionals is required."
        />
        <DirectiveTable directives={directives} />
      </div>
    </div>
  );
}
