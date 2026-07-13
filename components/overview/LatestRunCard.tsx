import Link from "next/link";
import { CheckCircle2 } from "lucide-react";
import StatusBadge from "@/components/ui/StatusBadge";
import type { LatestRunViewModel } from "@/lib/dashboard-view-model";

export default function LatestRunCard({ run }: { run: LatestRunViewModel }) {
  return <section className="rounded-xl border border-border bg-surface p-5" aria-labelledby="latest-run-title"><div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><CheckCircle2 className="h-5 w-5 text-success" aria-hidden="true" /><h2 id="latest-run-title" className="font-bold text-primary">Latest committed run</h2></div><StatusBadge label={run.status} variant="success" /></div><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2"><div><dt className="text-xs text-text-muted">Validation</dt><dd className="mt-0.5 text-primary">{run.validationStatus}</dd></div><div><dt className="text-xs text-text-muted">Accepted model period</dt><dd className="mt-0.5 text-primary">{run.acceptedPeriod}</dd></div><div><dt className="text-xs text-text-muted">Committed</dt><dd className="mt-0.5 text-primary">{new Date(run.timestamp).toLocaleString()}</dd></div><div><dt className="text-xs text-text-muted">Run ID</dt><dd className="mt-0.5 truncate font-mono text-xs text-secondary" title={run.runId}>{run.runId}</dd></div></dl><Link href="/validation" className="mt-4 inline-block text-sm font-semibold text-accent hover:underline">Review evidence</Link></section>;
}
