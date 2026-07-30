"use client";

import {useEffect,useState} from "react";
import StatusBadge from "@/components/ui/StatusBadge";
import {getMonitoringSummary} from "@/lib/runtime/client";
import type {MonitoringSummaryResponse} from "@/lib/runtime/contracts";
import {modelLabel} from "@/lib/status-labels";

const KNOWN_SOURCES=new Set(["quick_forecast_p1","quick_forecast_p2","approved_forecast_p1","approved_forecast_p2"]);
const metric=(value:number|null|undefined,digits=2)=>value==null?"Not available":value.toFixed(digits);
const sourceLabel=(value:string)=>({
  quick_forecast_p1:"Historical Quick Forecast",
  quick_forecast_p2:"Governed Quick Forecast",
  approved_forecast_p1:"Historical approved forecast",
  approved_forecast_p2:"Governed approved forecast",
}[value]??"Unknown source");

export default function ForecastOutcomeMonitoringSummary(){
  const[state,setState]=useState<MonitoringSummaryResponse|null>(null);
  useEffect(()=>{let active=true;getMonitoringSummary().then(value=>{if(active)setState(value)});return()=>{active=false}},[]);
  if(state==null)return <section className="mb-10 rounded-xl border border-border bg-surface p-5" aria-label="Forecast outcome monitoring"><p className="text-sm text-secondary">Loading governed outcome evidence…</p></section>;
  if(!state.ok){
    const awaiting=state.error.code==="monitoring_summary_not_found";
    return <section className="mb-10 rounded-xl border border-border bg-surface p-5" aria-label="Forecast outcome monitoring">
      <StatusBadge label={awaiting?"Awaiting outcomes":"Monitoring policy unavailable"} variant={awaiting?"warning":"destructive"}/>
      <h2 className="mt-3 text-xl font-bold text-primary">{awaiting?"Performance monitoring awaiting verified outcomes":"Monitoring policy unavailable"}</h2>
      <p className="mt-2 text-sm text-secondary">{awaiting?"No governed forecast outcome has been committed yet. This is an evidence-maturity state, not an invalid-policy or model-health finding.":state.error.message}</p>
    </section>;
  }
  const summary=state.summary;
  const sources=summary.sourceFamilyBreakdowns??[{identity:"quick_forecast_p1",evaluatedForecastCount:summary.evaluatedForecastCount,cumulativeMAE:summary.cumulativeMAE,cumulativeRMSE:summary.cumulativeRMSE,cumulativeBias:summary.cumulativeBias}];
  if(sources.some(item=>!KNOWN_SOURCES.has(item.identity)))return <section className="mb-10 rounded-xl border border-destructive/30 bg-destructive/10 p-5"><StatusBadge label="Unknown source rejected" variant="destructive"/><p className="mt-3 text-sm text-secondary">Monitoring evidence contains an unknown source family and is not displayed.</p></section>;
  const cards=[["Monitored",String(summary.evaluatedForecastCount)],["Pending actuals",String(summary.pendingOutcomeCount)],["MAE",metric(summary.cumulativeMAE)],["RMSE",metric(summary.cumulativeRMSE)],["Bias",metric(summary.cumulativeBias)],["MAPE",summary.cumulativeMAPE==null?"Not eligible":`${metric(summary.cumulativeMAPE)}%`]];
  return <section className="mb-10 rounded-2xl border border-border bg-surface p-6" aria-labelledby="forecast-monitoring-heading">
    <StatusBadge label="Verified outcome evidence" variant="info"/>
    <h2 id="forecast-monitoring-heading" className="mt-3 text-2xl font-bold text-primary">Forecast outcome monitoring</h2>
    <p className="mt-2 text-sm text-secondary">Exact-period actuals are compared with immutable runtime forecasts. This descriptive evidence does not classify model health, degradation, promotion, retention, replacement, or rollback.</p>
    <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">{cards.map(([name,value])=><div key={name} className="rounded-xl border border-border bg-background p-4"><p className="text-[10px] uppercase tracking-wider text-text-muted">{name}</p><p className="mt-2 text-lg font-bold text-primary">{value}</p></div>)}</div>
    <div className="mt-5 grid gap-5 lg:grid-cols-2"><div><h3 className="font-semibold text-primary">Source families</h3><ul className="mt-2 space-y-2 text-sm text-secondary">{sources.map(item=><li key={item.identity} className="flex justify-between gap-4"><span>{sourceLabel(item.identity)}</span><span>{item.evaluatedForecastCount} monitored</span></li>)}</ul></div><div><h3 className="font-semibold text-primary">Governed models</h3><ul className="mt-2 space-y-2 text-sm text-secondary">{summary.modelBreakdowns.map(item=><li key={item.identity} className="flex justify-between gap-4"><span>{modelLabel(item.identity.split("|")[0])}</span><span>MAE {metric(item.cumulativeMAE)}</span></li>)}</ul></div></div>
    <details className="mt-5 rounded-xl border border-border bg-background p-4 text-sm text-secondary"><summary className="cursor-pointer font-semibold text-primary">Technical evidence</summary><p className="mt-2">Policy version: {summary.policyVersion}. Latest target: {summary.latestEvaluatedTargetPeriod}. Percentage eligibility: {summary.percentageMetricEvaluatedCount}; zero outcomes excluded from percentage-only metrics: {summary.zeroObservedCount}.</p></details>
    <p className="mt-4 text-xs text-secondary">Protected observation submission remains trusted server-side ingress. This read-only panel contains no monitoring credential and triggers no lifecycle action.</p>
  </section>;
}
