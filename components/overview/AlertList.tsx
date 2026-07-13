import { AlertTriangle } from "lucide-react";
import EmptyState from "@/components/ui/EmptyState";
import type { AlertViewModel } from "@/lib/dashboard-view-model";

export default function AlertList({ alerts }: { alerts: AlertViewModel[] }) {
  return <section className="rounded-xl border border-border bg-surface p-5" aria-labelledby="alerts-title"><h2 id="alerts-title" className="text-lg font-bold text-primary">Active alerts</h2>{alerts.length ? <ul className="mt-3 space-y-2">{alerts.slice(0,3).map((alert) => <li key={alert.id} className="flex gap-3 rounded-lg border border-warning/25 bg-warning/10 p-3"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden="true" /><div><p className="text-sm font-semibold text-primary">{alert.facilityName} · <span className="text-warning">{alert.severity}</span></p><p className="mt-1 text-xs text-secondary">{alert.message}</p></div></li>)}</ul> : <div className="mt-3"><EmptyState title="No active inventory alerts" description="Stock-horizon review indicators may still be present; they are not critical alerts." /></div>}</section>;
}
