import { FlaskConical } from "lucide-react";
import ForecastRunWorkflow from "@/components/forecast/ForecastRunWorkflow";
import StatusBadge from "@/components/ui/StatusBadge";

export const metadata = { title: "New Forecast — DengueOps AI" };

export default function ForecastPage() {
  return <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8"><header className="mb-7 rounded-2xl border border-border bg-surface p-6"><div className="flex flex-wrap items-center gap-2"><StatusBadge label="Preview workflow" variant="info" /><StatusBadge label="Runtime connector pending P1.4" /></div><h1 className="mt-4 text-3xl font-bold text-primary">New Forecast</h1><p className="mt-2 max-w-3xl text-sm text-secondary">Preview local file inspection, workflow selection, and future review states. Selecting a file never changes the committed Overview.</p><div className="mt-4 flex gap-2 rounded-xl border border-warning/25 bg-warning/10 p-4 text-sm text-warning"><FlaskConical className="h-5 w-5 shrink-0" /><p>Random Forest is approved only for the current synthetic demonstration context. Materially different datasets require dataset-specific suitability assessment.</p></div></header><ForecastRunWorkflow /></div>;
}
