"use client";

import { useState } from "react";
import { BedDouble, Droplets, Info, PackageSearch, ShieldAlert } from "lucide-react";
import ScenarioSelector from "@/components/dashboard/ScenarioSelector";
import FacilityReadinessView from "@/components/dashboard/FacilityReadinessView";
import DirectiveTable from "@/components/dashboard/DirectiveTable";
import MetricCard from "@/components/ui/MetricCard";
import StatusBadge from "@/components/ui/StatusBadge";
import { preparednessViewModel } from "@/lib/demo-data";
import type { ScenarioKey } from "@/lib/types";

export default function PreparednessPage() {
  const [scenario,setScenario]=useState<ScenarioKey>("expected_case"); const vm=preparednessViewModel; const selected=vm.scenarios[scenario]; const suffix=scenario==="best_case"?"best":scenario==="worst_case"?"worst":"expected";
  const projected=vm.facilities.reduce((sum,d)=>sum+Number(d[`projected_bed_load_${suffix}` as keyof typeof d]??0),0); const gaps=vm.facilities.filter(d=>Number(d[`bed_gap_${suffix}` as keyof typeof d]??0)>0).length; const alerts=vm.facilities.reduce((sum,d)=>sum+d.inventory_alerts.length,0); const ns1=vm.facilities.filter(d=>Number(d[`sdh_ns1_${suffix}` as keyof typeof d]??Infinity)<=14).length; const iv=vm.facilities.filter(d=>Number(d[`sdh_iv_fluid_${suffix}` as keyof typeof d]??Infinity)<=14).length;
  return <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8"><header className="rounded-2xl border border-border bg-surface p-6"><div className="flex flex-wrap gap-2"><StatusBadge label="Planning compatibility" variant="info"/><StatusBadge label="Synthetic values" variant="warning"/></div><h1 className="mt-4 text-3xl font-bold text-primary">Preparedness</h1><p className="mt-2 max-w-3xl text-sm text-secondary">Review planning sensitivity, facility bed readiness, stock horizons, inventory alerts, and governed planning suggestions.</p></header>
    <aside className="flex gap-3 rounded-xl border border-informational/25 bg-informational/10 p-4"><Info className="h-5 w-5 shrink-0 text-informational"/><p className="text-sm text-ink">{vm.scenarioRelationship}</p></aside>
    <section className="rounded-xl border border-border bg-surface p-5"><h2 className="font-semibold text-primary">Planning Sensitivity Scenarios</h2><p className="mt-1 text-xs text-secondary">These values drive current operational compatibility logic; they are not the empirical forecast range.</p><div className="mt-4"><ScenarioSelector active={scenario} onChange={setScenario}/></div><div className="mt-5 grid grid-cols-2 gap-3 xl:grid-cols-6"><MetricCard title="Planning cases" value={selected.forecast_cases} subtitle="Operational input" variant="info"/><MetricCard title="Projected bed demand" value={projected.toFixed(1)} subtitle="Network total" icon={<BedDouble className="h-4 w-4"/>}/><MetricCard title="Facilities in deficit" value={gaps} subtitle={`${vm.facilities.length} configured facilities`} variant={gaps?"warning":"success"} icon={<ShieldAlert className="h-4 w-4"/>}/><MetricCard title="NS1/RDT horizon ≤14 days" value={ns1} subtitle={`of ${vm.facilities.length} facilities`} variant={ns1?"warning":"success"} icon={<PackageSearch className="h-4 w-4"/>}/><MetricCard title="IV-fluid horizon ≤14 days" value={iv} subtitle={`of ${vm.facilities.length} facilities`} variant={iv?"warning":"success"} icon={<Droplets className="h-4 w-4"/>}/><MetricCard title="Inventory alerts" value={alerts} subtitle="Current generated directives" variant={alerts?"warning":"success"} icon={<PackageSearch className="h-4 w-4"/>}/></div></section>
    <FacilityReadinessView directives={vm.facilities}/>
    <section><h2 className="mb-4 text-xl font-bold text-ink">Planning suggestions</h2><DirectiveTable directives={vm.facilities}/></section>
  </div>;
}
