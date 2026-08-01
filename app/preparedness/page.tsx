"use client";

import {useEffect,useState} from "react";
import StatusBadge from "@/components/ui/StatusBadge";
import OperationalPreparednessTable from "@/components/overview/OperationalPreparednessTable";
import FacilityReadinessView from "@/components/dashboard/FacilityReadinessView";
import DirectiveTable from "@/components/dashboard/DirectiveTable";
import {preparednessViewModel} from "@/lib/demo-data";
import type {OverviewViewModel} from "@/lib/dashboard-view-model";
import {getLatestDashboard} from "@/lib/runtime/client";

export default function PreparednessPage(){
  const [current,setCurrent]=useState<{status:"loading"}|{status:"ready";vm:OverviewViewModel}|{status:"unavailable";reason:string}>({status:"loading"});
  useEffect(()=>{let active=true;void getLatestDashboard().then(result=>{if(!active)return;if(result.ok)setCurrent({status:"ready",vm:result.dashboard});else setCurrent({status:"unavailable",reason:result.error.message})}).catch(()=>active&&setCurrent({status:"unavailable",reason:"Current operational preparedness could not be verified."}));return()=>{active=false}},[]);
  return <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
    <header className="rounded-2xl border border-border bg-surface p-6"><div className="flex flex-wrap gap-2"><StatusBadge label="Governed planning" variant="info"/><StatusBadge label="Evidence-separated" variant="warning"/></div><h1 className="mt-4 text-3xl font-bold text-primary">Preparedness</h1><p className="mt-2 max-w-3xl text-sm text-secondary">Current operational planning is kept separate from synthetic qualification and historical demonstration evidence.</p></header>
    <section aria-labelledby="current-preparedness-title" className="space-y-4"><h2 id="current-preparedness-title" className="text-xl font-bold text-primary">Current operational preparedness</h2>{current.status==="loading"?<div className="rounded-xl border border-border bg-surface p-5" aria-live="polite">Verifying current preparedness authority…</div>:current.status==="unavailable"||current.vm.preparedness.availabilityStatus!=="available"?<div className="rounded-xl border border-warning/25 bg-warning/10 p-5"><h3 className="font-semibold text-primary">Preparedness unavailable</h3><p className="mt-2 text-sm text-secondary">{current.status==="unavailable"?current.reason:current.vm.preparedness.reason}</p></div>:<><p className="text-sm text-secondary">{current.vm.preparedness.formulaLabel}. Current live availability is not reported.</p><OperationalPreparednessTable rows={current.vm.preparedness.rows}/></>}</section>
    <section className="rounded-xl border border-warning/25 bg-warning/10 p-5"><h2 className="font-semibold text-primary">Qualification preparedness evidence</h2><p className="mt-2 text-sm text-secondary">Synthetic qualification only. Operational use prohibited. The governed 13-hospital cohort and baseline, constrained, and severe scenarios remain verification evidence and never satisfy current authority.</p></section>
    <details className="rounded-xl border border-border bg-surface p-5"><summary className="cursor-pointer font-semibold text-primary">Historical/demo evidence</summary><p className="mt-3 text-sm text-secondary">Bundled directives below are historical demonstration evidence, not current hospital availability or operational preparedness.</p><div className="mt-5 space-y-6"><FacilityReadinessView directives={preparednessViewModel.facilities}/><section><h3 className="mb-4 text-lg font-bold text-primary">Historical planning suggestions</h3><DirectiveTable directives={preparednessViewModel.facilities}/></section></div></details>
  </div>;
}
