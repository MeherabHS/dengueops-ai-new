import EmptyState from "@/components/ui/EmptyState";
import ErrorState from "@/components/ui/ErrorState";
import Button from "@/components/ui/Button";
import type { ForecastRunResult } from "@/lib/forecast-workflow-types";

export default function ForecastResultSummary({ result }: { result: ForecastRunResult | null }) {
  if (!result) return <EmptyState title="No committed runtime result" description="A result appears only after the isolated worker validates and commits the complete run." />;
  if (result.status === "failed") return <ErrorState title="Run failed" description={result.error ?? "The runtime connector reported a failure."} />;
  return <div className="rounded-xl border border-success/25 bg-success/10 p-5"><h2 className="font-semibold text-ink">Point forecast committed</h2><p className="mt-1 text-sm text-ink-muted">Run {result.runId}</p><dl className="mt-4 grid gap-3 text-sm sm:grid-cols-3"><div><dt className="text-text-muted">Forecast</dt><dd className="font-semibold text-primary">{result.forecast?.point} cases</dd></div><div><dt className="text-text-muted">Empirical range</dt><dd className="font-semibold text-warning">Unavailable — calibration pending</dd></div><div><dt className="text-text-muted">Preparedness</dt><dd className="font-semibold text-warning">Unavailable — policy pending</dd></div></dl><Button href="/dashboard" className="mt-5">Open committed Overview</Button></div>;
}
