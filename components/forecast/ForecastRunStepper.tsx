import type { WorkflowStep } from "@/lib/forecast-workflow-types";

const steps: Array<{ id: WorkflowStep; label: string }> = [
  { id: "upload", label: "Upload" }, { id: "validate", label: "Validate" }, { id: "choose", label: "Choose Workflow" }, { id: "review", label: "Review and Execute" }, { id: "results", label: "Results" },
];
export default function ForecastRunStepper({ current }: { current: WorkflowStep }) {
  const active = steps.findIndex(s => s.id === current);
  return <ol className="grid gap-2 sm:grid-cols-5" aria-label="Forecast workflow progress">
    {steps.map((step,index) => <li key={step.id} aria-current={current === step.id ? "step" : undefined} className={`rounded-lg border px-3 py-3 text-xs font-semibold ${index === active ? "border-accent bg-accent/10 text-accent" : index < active ? "border-success/25 bg-success/10 text-success" : "border-border-subtle bg-surface text-ink-muted"}`}><span className="mr-2 font-mono">{index + 1}</span>{step.label}</li>)}
  </ol>;
}
