import StatusBadge from "@/components/ui/StatusBadge";

export default function QuickForecastOption({ selected }: { selected: boolean }) {
  return <div>
    <div className="flex items-center justify-between gap-2">
      <h3 className="font-semibold text-primary">Quick Forecast</h3>
      {selected ? <StatusBadge label="Selected" variant="info" /> : null}
    </div>
    <p className="mt-2 text-sm text-secondary">Uses the current assigned model under its separate governed compatibility contract.</p>
    <dl className="mt-3 space-y-1 text-xs text-secondary">
      <div><dt className="inline font-semibold text-primary">Model authority: </dt><dd className="inline">Current assigned model, resolved by the server</dd></div>
      <div><dt className="inline font-semibold text-primary">B9.4B status: </dt><dd className="inline">Pending; this workflow does not start Quick Forecast</dd></div>
    </dl>
    <p className="mt-3 text-xs font-medium text-warning">Complete governed assignment in B9.4C before using this separate path.</p>
  </div>;
}
