import StatusBadge from "@/components/ui/StatusBadge";

export default function DatasetAssessmentOption({ selected }: { selected: boolean }) {
  return <div><div className="flex items-center justify-between gap-2"><h3 className="font-semibold text-primary">Assess Dataset</h3>{selected && <StatusBadge label="Selected" variant="info" />}</div><p className="mt-2 text-sm text-secondary">Evaluates model suitability for the uploaded historical dataset.</p><ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-secondary"><li>History sufficiency and temporal fold generation</li><li>Candidate comparison and dataset-specific recommendation</li><li>Recommendation strength, limitations, and human approval</li></ul><p className="mt-3 text-xs font-medium text-warning">Runtime model assessment is not yet connected in this UI phase.</p></div>;
}
