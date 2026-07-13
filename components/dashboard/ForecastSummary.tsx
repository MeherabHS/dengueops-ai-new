import { TrendingUp, Activity, MapPin, AlertTriangle, BedDouble } from "lucide-react";
import MetricCard from "@/components/ui/MetricCard";
import RiskBadge from "@/components/ui/RiskBadge";
import type { ForecastOutput, Directive, ScenarioKey } from "@/lib/types";
import { formatNumber, formatGrowthFactor } from "@/lib/formatters";

interface Props {
  forecast: ForecastOutput;
  directives: Directive[];
  scenario: ScenarioKey;
}

export default function ForecastSummary({ forecast, directives, scenario }: Props) {
  const sc = forecast.preparedness_scenarios[scenario];
  const criticalAlerts = directives.flatMap((d) =>
    d.inventory_alerts.filter((a) => a.alert_level === "Critical")
  );
  const bedGapFacilities = directives.filter((d) => d.bed_gap_expected > 0).length;
  const topZone = [...directives].sort((a, b) => b.priority_score - a.priority_score)[0];

  const isExpected = scenario === "expected_case";
  const isWorst = scenario === "worst_case";

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <MetricCard
        title="Forecasted Cases"
        value={formatNumber(sc.forecast_cases)}
        subtitle={`Epi Week ${forecast.target_epi_week}, ${forecast.target_epi_year}`}
        icon={<Activity className="h-4 w-4" />}
        variant={isWorst ? "critical" : isExpected ? "warning" : "success"}
      />
      <MetricCard
        title="Growth Factor"
        value={formatGrowthFactor(sc.growth_factor)}
        subtitle="vs baseline period"
        icon={<TrendingUp className="h-4 w-4" />}
        variant={sc.growth_factor >= 2 ? "critical" : sc.growth_factor >= 1.5 ? "warning" : "success"}
      />
      <MetricCard
        title="Risk Level"
        value={<RiskBadge level={sc.risk_level} size="sm" />}
        subtitle={`Risk score: ${sc.risk_score}/100`}
        variant={
          sc.risk_level === "Critical"
            ? "critical"
            : sc.risk_level === "High"
            ? "warning"
            : "default"
        }
      />
      <MetricCard
        title="Highest Priority Zone"
        value={topZone?.zone_name ?? "—"}
        subtitle={`Priority score: ${topZone?.priority_score.toFixed(2)}`}
        icon={<MapPin className="h-4 w-4" />}
        variant="info"
        className="col-span-1"
      />
      <MetricCard
        title="Critical Supply Alerts"
        value={criticalAlerts.length}
        subtitle="Items below 7-day threshold"
        icon={<AlertTriangle className="h-4 w-4" />}
        variant={criticalAlerts.length > 0 ? "critical" : "success"}
      />
      <MetricCard
        title="Facilities w/ Bed Gap"
        value={`${bedGapFacilities} / ${directives.length}`}
        subtitle="Projected bed deficit"
        icon={<BedDouble className="h-4 w-4" />}
        variant={bedGapFacilities >= 3 ? "critical" : bedGapFacilities > 0 ? "warning" : "success"}
      />
    </div>
  );
}
