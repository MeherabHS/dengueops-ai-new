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
import type { HistoricalCasePoint, MonitoringViewModel } from "@/lib/dashboard-view-model";

interface Props {
  history: HistoricalCasePoint[];
  targetPeriod: string;
  forecast: number;
  lower: number | null;
  upper: number | null;
  confidence: MonitoringViewModel["confidence"];
  driftStatus: MonitoringViewModel["featureDrift"]["status"];
}

type ChartPoint={period:string;observed:number|null;connector:number|null;forecast:number|null;rangeCenter:number|null;rangeError:number|null;confidenceScore:number|null;confidenceBand:string|null;driftStatus:string|null;lower:number|null;upper:number|null};

function label(value:string):string{return value.split("_").map(part=>part.charAt(0).toUpperCase()+part.slice(1)).join(" ")}
function ForecastTooltip({active,payload,period}:{active?:boolean;payload?:ReadonlyArray<{payload?:ChartPoint}>;period?:string|number}){
  if(!active||!payload?.length)return null;const point=payload.find(item=>item.payload)?.payload;if(!point)return null;
  return <div className="rounded-lg border border-border bg-surface-raised p-3 text-xs text-primary shadow-lg"><p className="font-semibold">{period}</p>{point.observed!==null?<p className="mt-1">Observed: {point.observed} cases</p>:<><p className="mt-1">Forecast: {point.forecast} cases</p>{point.lower!==null&&point.upper!==null?<p className="mt-1">Expected range: {point.lower}–{point.upper}</p>:<p className="mt-1 text-warning">Prediction interval unavailable</p>}{point.confidenceScore!==null?<p className="mt-1">Forecast confidence: {point.confidenceScore} / 100 — {label(point.confidenceBand??"")}</p>:<p className="mt-1">Forecast confidence: {point.confidenceBand==="pending"?"Calculating…":"Not available"}</p>}<p className="mt-1">Input drift: {label(point.driftStatus??"unavailable")}</p></>}</div>;
}

export default function ForecastTrendChart({ history, targetPeriod, forecast, lower, upper, confidence, driftStatus }: Props) {
  const [reduceMotion, setReduceMotion] = useState(true);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduceMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const rangeAvailable=lower!==null&&upper!==null&&Number.isFinite(lower)&&Number.isFinite(upper)&&lower<=upper;
  const data = useMemo<ChartPoint[]>(() => {
    const visible = history.slice(-16);
    return [
      ...visible.map((point, index) => ({
        period: point.period,
        observed: point.cases,
        connector: index === visible.length - 1 ? point.cases : null,
        forecast: null,
        rangeCenter: null,
        rangeError: null,
        confidenceScore:null,confidenceBand:null,driftStatus:null,lower:null,upper:null,
      })),
      {
        period: targetPeriod,
        observed: null,
        connector: forecast,
        forecast,
        rangeCenter: rangeAvailable ? (lower + upper) / 2 : null,
        rangeError: rangeAvailable ? (upper - lower) / 2 : null,
        confidenceScore:confidence.status==="available"?confidence.score:null,
        confidenceBand:confidence.status==="available"?confidence.band:confidence.status==="pending"?"pending":null,
        driftStatus,lower:rangeAvailable?lower:null,upper:rangeAvailable?upper:null,
      },
    ];
  }, [confidence,driftStatus,forecast, history, lower, rangeAvailable, targetPeriod, upper]);
  const summary = `Observed cases end at ${history.at(-1)?.cases ?? "an unavailable value"}. The committed forecast is ${forecast} cases for ${targetPeriod}.${rangeAvailable ? ` The calibrated prediction interval is ${lower} to ${upper}.` : " Prediction interval unavailable — model-specific calibration has not yet been completed."}${confidence.status==="available"?` Forecast evidence confidence is ${confidence.score} out of 100, ${label(confidence.band??"")}.`:confidence.status==="pending"?" Forecast evidence confidence is calculating.":" Forecast evidence confidence is unavailable."}`;
  return (
    <figure>
      <div className="h-80 min-w-0" aria-hidden="true">
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart data={data} margin={{ top: 18, right: 18, bottom: 8, left: -12 }}>
            <CartesianGrid stroke={CHART_COLORS.grid} strokeDasharray="3 6" vertical={false} />
            <XAxis dataKey="period" tick={{ fontSize: 10, fill: CHART_COLORS.muted }} tickLine={false} axisLine={false} minTickGap={28} />
            <YAxis tick={{ fontSize: 11, fill: CHART_COLORS.muted }} tickLine={false} axisLine={false} domain={[0, "auto"]} />
            <Tooltip content={(props)=><ForecastTooltip active={props.active} payload={props.payload as unknown as ReadonlyArray<{payload?:ChartPoint}>|undefined} period={props.label}/>} />
            <Legend wrapperStyle={{ color: CHART_COLORS.muted, fontSize: 12 }} />
            <Line type="monotone" dataKey="observed" name="Observed" stroke={CHART_COLORS.observed} strokeWidth={2.5} dot={false} isAnimationActive={!reduceMotion} animationDuration={700} />
            <Line type="linear" dataKey="connector" name="Forecast" stroke={CHART_COLORS.forecast} strokeWidth={2} strokeDasharray="6 5" dot={false} connectNulls isAnimationActive={!reduceMotion} animationBegin={650} animationDuration={420} />
            <Scatter dataKey="forecast" name="Current forecast" fill={CHART_COLORS.forecast} isAnimationActive={!reduceMotion} animationBegin={1050} animationDuration={250} />
            {rangeAvailable?<Scatter dataKey="rangeCenter" name="Prediction interval" fill={CHART_COLORS.range} isAnimationActive={!reduceMotion} animationBegin={1200} animationDuration={400}>
              <ErrorBar dataKey="rangeError" direction="y" width={14} stroke={CHART_COLORS.forecast} strokeWidth={7} />
            </Scatter>:null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-3 text-xs leading-relaxed text-text-muted">{summary}</figcaption>
    </figure>
  );
}
