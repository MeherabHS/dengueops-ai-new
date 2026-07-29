import StatusBadge from "@/components/ui/StatusBadge";

export default function DatasetAssessmentOption({ selected }: { selected: boolean }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-primary">Assess Dataset</h3>
        {selected ? <StatusBadge label="Selected" variant="info" /> : null}
      </div>
      <p className="mt-2 text-sm text-secondary">
        Runs the current governed temporal assessment for an eligible uploaded historical dataset.
      </p>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-secondary">
        <li>All governed candidates use the same immutable fold plan.</li>
        <li>The policy determines the bounded fold count and retains older rows in expanding training.</li>
        <li>The technical winner is derived from this dataset&apos;s assessment performance.</li>
        <li>Assessment does not automatically deploy or adopt a model.</li>
        <li>A separate Super User decision is required before one approved forecast can run.</li>
      </ul>
    </div>
  );
}
