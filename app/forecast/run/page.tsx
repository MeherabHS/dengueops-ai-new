import { ShieldCheck } from "lucide-react";
import OperationalForecastWorkflow from "@/components/forecast/OperationalForecastWorkflow";
import StatusBadge from "@/components/ui/StatusBadge";

export const metadata = { title: "Run Operational Forecast — DengueOps AI" };

export default function OperationalForecastPage() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-7 rounded-2xl border border-border bg-surface p-6">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge label="Operational forecast workflow" variant="info" />
          <StatusBadge label="Current governed assignment" />
        </div>
        <h1 className="mt-4 text-3xl font-bold text-primary">Run Operational Forecast</h1>
        <p className="mt-2 max-w-3xl text-sm text-secondary">Upload the latest Dhaka data, validate it against the current governed model assignment, run one operational forecast, and verify the exact committed run before opening the dashboard.</p>
        <div className="mt-4 flex gap-2 rounded-xl border border-warning/25 bg-warning/10 p-4 text-sm text-warning">
          <ShieldCheck className="h-5 w-5 shrink-0" aria-hidden="true" />
          <p>The assigned model is resolved from authenticated server authority. No model selector or browser-supplied model identity is permitted.</p>
        </div>
      </header>
      <OperationalForecastWorkflow />
    </div>
  );
}
