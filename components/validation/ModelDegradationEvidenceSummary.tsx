"use client";

import {useEffect,useState} from "react";
import StatusBadge from "@/components/ui/StatusBadge";
import {getModelDegradationEvidence} from "@/lib/runtime/client";
import type {ModelDegradationResponse} from "@/lib/runtime/contracts";
import {modelLabel} from "@/lib/status-labels";

const SOURCES=new Set(["quick_forecast_p1","quick_forecast_p2","approved_forecast_p1","approved_forecast_p2"]);
const WINDOW="window_size_not_governed";
const number=(value:number|null|undefined,digits=2)=>value==null?"Unavailable":value.toFixed(digits);
const change=(value:number)=>value>0?`increased by ${number(value)}`:value<0?`decreased by ${number(Math.abs(value))}`:"unchanged";
const basisLabel=(value:string)=>value==="published_prediction_to_observed_forecast_raw"?"Published prediction compared with verified observed values":"Value-basis evidence unavailable";
const sourceLabel=(value:string)=>value==="quick_forecast_p2"?"Governed Quick Forecast":value==="approved_forecast_p2"?"Governed approved forecast":value==="quick_forecast_p1"?"Historical Quick Forecast":"Historical approved forecast";

export default function ModelDegradationEvidenceSummary(){
  const[state,setState]=useState<ModelDegradationResponse|null>(null);
  useEffect(()=>{let active=true;getModelDegradationEvidence().then(value=>{if(active)setState(value)});return()=>{active=false}},[]);
  if(state==null)return <section className="mb-10 rounded-xl border border-border bg-surface p-5" aria-label="Model performance comparison evidence"><p className="text-sm text-secondary">Loading governed comparison evidence…</p></section>;
  if(!state.ok){
    const missing=state.error.code==="model_degradation_evidence_not_found";
    return <section className="mb-10 rounded-xl border border-border bg-surface p-5" aria-label="Model performance comparison evidence">
      <StatusBadge label={missing?"Evidence not generated":"Monitoring policy unavailable"} variant={missing?"warning":"destructive"}/>
      <h2 className="mt-3 text-xl font-bold text-primary">{missing?"Model-degradation evidence unavailable":"Monitoring policy unavailable"}</h2>
      <p className="mt-2 text-sm text-secondary">{missing?"No immutable comparison bundle exists yet. Historical benchmark metrics are not substituted for current outcome evidence.":state.error.message}</p>
    </section>;
  }
  const{evidence,summary}=state;
  if(evidence.evidenceStatus!=="evidence_only"||evidence.materialWorseningStatus!=="not_governed"||evidence.lifecycleActionStatus!=="prohibited_not_generated"||evidence.cohorts.some(cohort=>!SOURCES.has(cohort.identity.sourceFamily)||cohort.monitoringWindow.status!==WINDOW))return <section className="mb-10 rounded-xl border border-destructive/30 bg-destructive/10 p-5"><StatusBadge label="Unknown evidence rejected" variant="destructive"/><p className="mt-3 text-sm text-secondary">The comparison bundle contains an unknown identity or state and is not displayed.</p></section>;
  return <section className="mb-10 rounded-2xl border border-border bg-surface p-6" aria-labelledby="model-comparison-heading">
    <div className="flex flex-wrap gap-2"><StatusBadge label="Evidence only" variant="info"/><StatusBadge label="No lifecycle decision" variant="warning"/></div>
    <h2 id="model-comparison-heading" className="mt-3 text-2xl font-bold text-primary">Model-degradation evidence</h2>
    <p className="mt-2 text-sm text-secondary">Assessment-reference evidence and current outcome evidence remain separate. No material-worsening conclusion, model-health label, or deployment action is produced.</p>
    <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><div className="rounded-xl border border-border bg-background p-4"><p className="text-xs text-text-muted">Verified outcomes</p><p className="mt-1 text-xl font-bold text-primary">{summary.verifiedOutcomeCount}</p></div><div className="rounded-xl border border-border bg-background p-4"><p className="text-xs text-text-muted">Strict cohorts</p><p className="mt-1 text-xl font-bold text-primary">{summary.cohortCount}</p></div><div className="rounded-xl border border-border bg-background p-4"><p className="text-xs text-text-muted">Assessment references</p><p className="mt-1 text-xl font-bold text-primary">{summary.assessmentReferenceDimensionCount}</p></div><div className="rounded-xl border border-border bg-background p-4"><p className="text-xs text-text-muted">Latest target</p><p className="mt-1 text-xl font-bold text-primary">{summary.latestTargetPeriod}</p></div></div>
    <div className="mt-6 space-y-5">{evidence.cohorts.map(cohort=><article key={cohort.cohortId} className="rounded-xl border border-border bg-background p-5"><h3 className="font-semibold text-primary">{modelLabel(cohort.identity.modelId)} · {sourceLabel(cohort.identity.sourceFamily)}</h3><div className="mt-4 grid gap-4 lg:grid-cols-2"><div><h4 className="text-sm font-semibold text-primary">Assessment-reference evidence</h4>{cohort.assessmentReferences.length===0?<p className="mt-2 text-sm text-secondary">Not applicable: Quick Forecast has no committed assessment reference.</p>:cohort.assessmentReferences.map(reference=><div key={reference.assessmentId} className="mt-2 rounded-lg border border-border p-3 text-sm text-secondary"><p>Period {reference.selectedEvaluationPeriod.start}–{reference.selectedEvaluationPeriod.end}; {reference.plannedFoldCount} successful folds; {reference.observedOutcomeCount} observed outcome(s).</p><p className="mt-1">MAE: assessment {number(reference.assessmentMAE)}, observed {number(reference.observedMAE)} — {change(reference.maeDelta)}; ratio {number(reference.maeRatio)}.</p><p className="mt-1">RMSE: assessment {number(reference.assessmentRMSE)}, observed {number(reference.observedRMSE)} — {change(reference.rmseDelta)}; ratio {number(reference.rmseRatio)}.</p><p className="mt-1">Comparability is limited across assessment and observed populations. {basisLabel(reference.forecastValueBasisStatus)}. Sample sufficiency is not governed.</p></div>)}</div><div><h4 className="text-sm font-semibold text-primary">Monitoring-window evidence</h4><p className="mt-2 text-sm text-secondary">Unavailable: no numerical window size is governed. No recent/reference metrics were calculated, and no adaptive window was selected.</p><p className="mt-2 text-sm text-secondary">Percentage eligibility: {cohort.actualPopulation.percentageEligibleCount}. Range eligibility: {cohort.actualPopulation.rangeEligibleCount}.</p></div></div><details className="mt-4 text-xs text-secondary"><summary className="cursor-pointer font-semibold text-primary">Technical evidence</summary><p className="mt-2">Model family: {cohort.identity.modelFamily}. Parameter SHA: {cohort.identity.parameterSha256}. Source family: {cohort.identity.sourceFamily}. Policy version: {evidence.degradationPolicy.policyVersion}.</p>{cohort.warnings.length?<p className="mt-2">Reason codes: {cohort.warnings.join("; ")}.</p>:null}</details></article>)}</div>
    <p className="mt-5 text-xs text-secondary">This read-only panel contains no monitoring credential, submits no evidence job, and cannot trigger a lifecycle or deployment-model action.</p>
  </section>;
}
