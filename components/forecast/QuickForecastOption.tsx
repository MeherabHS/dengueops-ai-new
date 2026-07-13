import StatusBadge from "@/components/ui/StatusBadge";

export default function QuickForecastOption({ selected }: { selected: boolean }) {
  return <div><div className="flex items-center justify-between gap-2"><h3 className="font-semibold text-primary">Quick Forecast</h3>{selected && <StatusBadge label="Selected" variant="info" />}</div><p className="mt-2 text-sm text-secondary">Uses the currently approved model for this deployment context.</p><dl className="mt-3 space-y-1 text-xs text-secondary"><div><dt className="inline font-semibold text-primary">Current approved model: </dt><dd className="inline">Random Forest</dd></div><div><dt className="inline font-semibold text-primary">Context: </dt><dd className="inline">Synthetic capability demonstration · Benchmark only</dd></div></dl><p className="mt-3 text-xs font-medium text-warning">This option does not reassess whether Random Forest is the best model for a materially different dataset.</p></div>;
}
