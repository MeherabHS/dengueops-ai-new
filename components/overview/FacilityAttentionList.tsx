import Link from "next/link";
import { ArrowRight, Building2 } from "lucide-react";
import EmptyState from "@/components/ui/EmptyState";
import StatusBadge from "@/components/ui/StatusBadge";
import type { FacilityAttentionViewModel } from "@/lib/dashboard-view-model";

export default function FacilityAttentionList({ facilities }: { facilities: FacilityAttentionViewModel[] }) {
  return <section aria-labelledby="facility-attention-title"><div className="mb-4 flex items-end justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wider text-accent">Network attention</p><h2 id="facility-attention-title" className="mt-1 text-xl font-bold text-primary">Facilities requiring attention</h2></div><Link href="/preparedness" className="inline-flex items-center gap-1 text-sm font-semibold text-accent hover:underline">View preparedness <ArrowRight className="h-4 w-4" /></Link></div>
    {facilities.length ? <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">{facilities.slice(0,4).map((facility) => <article key={facility.id} className="rounded-xl border border-border bg-surface p-4"><div className="flex items-start gap-3"><Building2 className="mt-0.5 h-5 w-5 shrink-0 text-accent" /><div className="min-w-0 flex-1"><div className="flex flex-wrap items-start justify-between gap-2"><h3 className="font-semibold text-primary">{facility.name}</h3><StatusBadge label={facility.status} variant={facility.status === "Critical" || facility.status === "Deficit" ? "destructive" : "warning"} /></div><p className="mt-2 text-xs text-secondary">{facility.configuredBeds} configured beds · {facility.projectedDemand.toFixed(1)} projected demand</p><p className="mt-2 text-sm font-medium text-primary">{facility.reserveOrDeficit >= 0 ? `${facility.reserveOrDeficit.toFixed(1)} bed reserve` : `${Math.abs(facility.reserveOrDeficit).toFixed(1)} bed deficit`}</p><p className="mt-1 text-xs text-text-muted">{facility.statusReason}</p></div></div></article>)}</div> : <EmptyState title="No facilities currently require review" description="The latest committed planning output contains no governed review condition." />}
  </section>;
}
