import type { WorkflowStep } from "@/lib/forecast-workflow-types";

const steps: Array<{ id: WorkflowStep; label: string }> = [
  { id: "upload", label: "Upload" },
  { id: "validation", label: "Validation" },
  { id: "assessment", label: "Assessment" },
  { id: "ranking", label: "Ranking" },
  { id: "decision", label: "Decision" },
  { id: "approved_forecast", label: "Approved forecast" },
  { id: "assignment", label: "Assignment" },
  { id: "quick_forecast", label: "Quick Forecast" },
  { id: "complete", label: "Complete" },
];

export default function ForecastRunStepper({ current, completedThrough }: { current: WorkflowStep; completedThrough: WorkflowStep | null }) {
  const active = steps.findIndex((step) => step.id === current);
  const completed = completedThrough ? steps.findIndex((step) => step.id === completedThrough) : -1;
  return <ol className="grid gap-2 sm:grid-cols-3 xl:grid-cols-9" aria-label="Forecast workflow progress">
    {steps.map((step, index) => {
      const isComplete = index <= completed;
      const isCurrent = index === active;
      return <li
        key={step.id}
        aria-current={isCurrent ? "step" : undefined}
        data-stage-state={isComplete ? "complete" : isCurrent ? "current" : "pending"}
        className={`rounded-lg border px-3 py-3 text-xs font-semibold ${isComplete ? "border-success/25 bg-success/10 text-success" : isCurrent ? "border-accent bg-accent/10 text-accent" : "border-border-subtle bg-surface text-ink-muted"}`}
      >
        <span className="mr-2 font-mono">{index + 1}</span>{step.label}
      </li>;
    })}
  </ol>;
}
