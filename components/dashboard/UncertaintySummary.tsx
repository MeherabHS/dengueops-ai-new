import type { ForecastOutput } from "@/lib/types";

interface Props { forecast: ForecastOutput }

export default function UncertaintySummary({ forecast }: Props) {
  const range = forecast.forecast_uncertainty;
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
      <div className="border-b border-border bg-accent-soft px-4 py-3">
        <p className="text-sm font-semibold text-primary">Empirical forecast range — {forecast.horizon_days}-day horizon</p>
        <p className="mt-0.5 text-xs text-secondary">Prior-only expanding temporal evaluation on deterministic synthetic residuals.</p>
      </div>
      <div className="grid grid-cols-3 gap-3 p-4 text-center">
        <div><p className="text-xs text-muted">Lower</p><p className="text-2xl font-bold text-primary">{range.interval_lower_reported}</p></div>
        <div><p className="text-xs text-muted">Forecast</p><p className="text-2xl font-bold text-accent">{range.point_forecast_reported}</p></div>
        <div><p className="text-xs text-muted">Upper</p><p className="text-2xl font-bold text-primary">{range.interval_upper_reported}</p></div>
      </div>
      <div className="border-t border-border px-4 py-3 text-xs text-secondary">Temporally evaluated on synthetic data. Historical coverage does not guarantee future performance.</div>
    </div>
  );
}
