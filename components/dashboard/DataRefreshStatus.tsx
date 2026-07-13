import { Clock, Database, GitCommitHorizontal } from "lucide-react";
import { overviewViewModel } from "@/lib/demo-data";
import StatusBadge from "@/components/ui/StatusBadge";

function formatDisplayDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.valueOf())) return iso;
  return date.toLocaleString("en-GB", { timeZone: "Asia/Dhaka", dateStyle: "medium", timeStyle: "short" });
}

export default function DataRefreshStatus() {
  return <section className="rounded-xl border border-border bg-surface shadow-sm" aria-labelledby="data-status-heading">
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-surface-muted px-4 py-3"><GitCommitHorizontal className="h-4 w-4 text-accent" aria-hidden="true" /><h2 id="data-status-heading" className="text-xs font-semibold uppercase tracking-wide text-secondary">Latest committed data state</h2><StatusBadge variant="info" className="ml-auto">{overviewViewModel.latestRun.status}</StatusBadge></div>
    <dl className="grid gap-4 p-4 sm:grid-cols-3">
      <div><dt className="flex items-center gap-1.5 text-xs text-muted"><Clock className="h-3.5 w-3.5" />Generated</dt><dd className="mt-1 text-sm font-medium text-primary">{formatDisplayDate(overviewViewModel.latestRun.run_timestamp)}</dd></div>
      <div><dt className="flex items-center gap-1.5 text-xs text-muted"><Database className="h-3.5 w-3.5" />Data mode</dt><dd className="mt-1 text-sm font-medium text-primary">{overviewViewModel.deploymentMode}</dd></div>
      <div><dt className="text-xs text-muted">Run ID</dt><dd className="mt-1 break-all font-mono text-xs text-primary">{overviewViewModel.latestRun.runId}</dd></div>
    </dl>
  </section>;
}
