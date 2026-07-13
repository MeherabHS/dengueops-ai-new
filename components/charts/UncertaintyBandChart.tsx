"use client";

import type { ForecastOutput } from "@/lib/types";

interface Props { forecast: ForecastOutput; }

export default function UncertaintyBandChart({ forecast }: Props) {
  const range = forecast.forecast_uncertainty;
  const span = Math.max(1, range.interval_upper_reported - range.interval_lower_reported);
  const pointPosition = ((range.point_forecast_reported - range.interval_lower_reported) / span) * 100;
  return (
    <div className="flex h-[280px] flex-col justify-center px-5">
      <div className="relative h-3 rounded-full bg-sky-200">
        <div className="absolute -top-2 h-7 w-1 rounded bg-sky-700" style={{ left: `${pointPosition}%` }} />
      </div>
      <div className="mt-3 flex justify-between text-xs font-semibold text-slate-700">
        <span>{range.interval_lower_reported} lower</span><span>{range.point_forecast_reported} forecast</span><span>{range.interval_upper_reported} upper</span>
      </div>
      <p className="mt-6 text-center text-xs text-slate-500">Empirical range from the 90% nominal prior-residual rule. It is not a probability statement.</p>
    </div>
  );
}
