import { AlertTriangle, Check, CircleX, LoaderCircle } from "lucide-react";
import type { OperationalForecastStep, WorkflowStep } from "@/lib/forecast-workflow-types";

const governanceSteps: Array<{ id: WorkflowStep; label: string }> = [
  { id: "upload", label: "Upload" },
  { id: "validation", label: "Validation" },
  { id: "assessment", label: "Assessment" },
  { id: "ranking", label: "Ranking" },
  { id: "decision", label: "Decision" },
  { id: "qualification_run", label: "Qualification run" },
  { id: "assignment", label: "Assignment" },
  { id: "complete", label: "Complete" },
];

const operationalSteps: Array<{ id: OperationalForecastStep; label: string }> = [
  { id: "upload_latest_data", label: "Upload latest data" },
  { id: "validation", label: "Validation" },
  { id: "forecast", label: "Forecast" },
  { id: "current_verification", label: "Current verification" },
  { id: "complete", label: "Complete" },
];

export type ActiveStepState = "idle" | "busy" | "failed" | "conflict";
type StepId = WorkflowStep | OperationalForecastStep;

export default function ForecastRunStepper({ current, completedThrough, activeState = "idle", workflow = "governance" }: { current: StepId; completedThrough: StepId | null; activeState?: ActiveStepState; workflow?: "governance" | "operational" }) {
  const steps: Array<{ id: StepId; label: string }> = workflow === "operational" ? operationalSteps : governanceSteps;
  const active = steps.findIndex((step) => step.id === current);
  const completed = completedThrough ? steps.findIndex((step) => step.id === completedThrough) : -1;
  return <ol className={`grid gap-2 sm:grid-cols-2 ${workflow === "operational" ? "xl:grid-cols-5" : "xl:grid-cols-8"}`} aria-label={workflow === "operational" ? "Operational forecast workflow progress" : "Model assessment and assignment workflow progress"}>
    {steps.map((step, index) => {
      const isComplete = index <= completed;
      const isCurrent = index === active;
      return <li
        key={step.id}
        aria-current={isCurrent ? "step" : undefined}
        data-stage-state={isComplete ? "complete" : isCurrent ? "current" : "pending"}
        className={`rounded-lg border px-3 py-3 text-xs font-semibold ${isComplete ? "border-success/25 bg-success/10 text-success" : isCurrent ? "border-accent bg-accent/10 text-accent" : "border-border-subtle bg-surface text-ink-muted"}`}
      >
        <span className="mr-2 inline-flex h-4 w-4 items-center justify-center font-mono" aria-hidden="true">
          {isComplete ? <Check className="h-4 w-4" /> : isCurrent && activeState === "busy" ? <LoaderCircle className="h-4 w-4 animate-spin" /> : isCurrent && activeState === "failed" ? <CircleX className="h-4 w-4" /> : isCurrent && activeState === "conflict" ? <AlertTriangle className="h-4 w-4" /> : index + 1}
        </span>{step.label}
      </li>;
    })}
  </ol>;
}
