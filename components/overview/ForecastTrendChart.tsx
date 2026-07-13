"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  ErrorBar,
  Legend,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CHART_COLORS } from "@/lib/constants";
import type { HistoricalCasePoint } from "@/lib/dashboard-view-model";

interface Props {
  history: HistoricalCasePoint[];
  targetPeriod: string;
  forecast: number;
  lower: number | null;
  upper: number | null;
}

export default function ForecastTrendChart({ history, targetPeriod, forecast, lower, upper }: Props) {
  const [reduceMotion, setReduceMotion] = useState(true);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduceMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const data = useMemo(() => {
    const visible = history.slice(-16);
    return [
      ...visible.map((point, index) => ({
        period: point.period,
        observed: point.cases,
        connector: index === visible.length - 1 ? point.cases : null,
        forecast: null,
        rangeCenter: null,
        rangeError: null,
      })),
      {
        period: targetPeriod,
        observed: null,
        connector: forecast,
        forecast,
        rangeCenter: lower === null || upper === null ? null : (lower + upper) / 2,
        rangeError: lower === null || upper === null ? null : (upper - lower) / 2,
      },
    ];
  }, [forecast, history, lower, targetPeriod, upper]);
  const summary = `Observed cases end at ${history.at(-1)?.cases ?? "an unavailable value"}. The committed forecast is ${forecast} cases for ${targetPeriod}.${lower === null || upper === null ? " Dataset-specific empirical range evidence is unavailable." : ` The empirical range is ${lower} to ${upper}.`}`;
  return (
    <figure>
      <div className="h-80 min-w-0" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={data} margin={{ top: 18, right: 18, bottom: 8, left: -12 }}>
            <CartesianGrid stroke={CHART_COLORS.grid} strokeDasharray="3 6" vertical={false} />
            <XAxis dataKey="period" tick={{ fontSize: 10, fill: CHART_COLORS.muted }} tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis tick={{ fontSize: 11, fill: CHART_COLORS.muted }} tickLine={false} axisLine={false} domain={[0, "auto"]} />
            <Tooltip contentStyle={{ background: "var(--surface-raised)", border: "1px solid var(--border-subtle)", borderRadius: 10, color: "var(--text-primary)" }} />
            <Legend wrapperStyle={{ color: CHART_COLORS.muted, fontSize: 12 }} />
            <Line type="monotone" dataKey="observed" name="Observed" stroke={CHART_COLORS.observed} strokeWidth={2.5} dot={false} isAnimationActive={!reduceMotion} animationDuration={700} />
            <Line type="linear" dataKey="connector" name="Forecast connector" stroke={CHART_COLORS.forecast} strokeWidth={2} strokeDasharray="6 5" dot={false} connectNulls isAnimationActive={!reduceMotion} animationBegin={650} animationDuration={420} />
            <Scatter dataKey="forecast" name="Forecast" fill={CHART_COLORS.forecast} isAnimationActive={!reduceMotion} animationBegin={1050} animationDuration={250} />
            <Scatter dataKey="rangeCenter" name="Empirical range" fill={CHART_COLORS.range} isAnimationActive={!reduceMotion && lower !== null && upper !== null} animationBegin={1200} animationDuration={400}>
              <ErrorBar dataKey="rangeError" direction="y" width={14} stroke={CHART_COLORS.forecast} strokeWidth={7} />
            </Scatter>
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-3 text-xs leading-relaxed text-text-muted">{summary}</figcaption>
    </figure>
  );
}
