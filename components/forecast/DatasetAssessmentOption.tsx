import StatusBadge from "@/components/ui/StatusBadge";

export default function DatasetAssessmentOption({ selected }: { selected: boolean }) {
  return (
    <div>
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-primary">Assess Dataset</h3>
        {selected ? <StatusBadge label="Selected" variant="info" /> : null}
      </div>
      <p className="mt-2 text-sm text-secondary">
        Runs a governed 52-68 fold temporal assessment for an eligible uploaded historical dataset.
      </p>
      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-secondary">
        <li>All governed candidates use the same immutable fold plan.</li>
        <li>When more than 68 folds are available, the most recent 68 are evaluated while all older rows remain in expanding training.</li>
        <li>The technical winner is evidence only; recommendation strength remains unavailable.</li>
        <li>Assessment does not automatically deploy or adopt a model.</li>
        <li>Phase 2 assessments stop at immutable evidence until a compatible decision policy is approved.</li>
      </ul>
    </div>
  );
}
