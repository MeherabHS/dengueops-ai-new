import StatusBadge from "@/components/ui/StatusBadge";

export default function DatasetAssessmentOption({ selected }: { selected: boolean }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-primary">Assess Dataset</h3>
        {selected ? <StatusBadge label="Selected" variant="info" /> : null}
      </div>
      <p className="mt-2 text-sm text-secondary">
        Runs the governed 68-fold temporal assessment for an eligible uploaded historical dataset.
      </p>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-secondary">
        <li>All governed candidates use the same immutable fold plan.</li>
        <li>The technical winner is evidence only; recommendation strength remains unavailable.</li>
        <li>Assessment does not automatically deploy or adopt a model.</li>
        <li>Forecasting requires a separate trusted internal one-run decision.</li>
      </ul>
    </div>
  );
}
