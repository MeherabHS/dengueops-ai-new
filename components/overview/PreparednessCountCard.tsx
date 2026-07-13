import type { ReactNode } from "react";

export default function PreparednessCountCard({ label, affected, total, note, icon }: { label: string; affected: number; total: number; note: string; icon: ReactNode }) {
  const progress = total > 0 ? Math.min(100, (affected / total) * 100) : 0;
  return <article className="rounded-xl border border-border bg-surface p-4">
    <div className="flex items-start justify-between gap-3"><div><p className="text-xs font-medium text-secondary">{label}</p><p className="metric-enter mt-2 text-2xl font-bold text-primary">{affected} <span className="text-sm font-medium text-muted">of {total} facilities</span></p></div><span className="rounded-lg bg-surface-raised p-2 text-accent" aria-hidden="true">{icon}</span></div>
    <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-surface-raised" role="progressbar" aria-label={`${label}: ${affected} of ${total} facilities`} aria-valuemin={0} aria-valuemax={total} aria-valuenow={affected}><div className="h-full rounded-full bg-accent transition-[width] duration-500 motion-reduce:transition-none" style={{ width: `${progress}%` }} /></div>
    <p className="mt-2 text-xs text-text-muted">{note}</p>
  </article>;
}
