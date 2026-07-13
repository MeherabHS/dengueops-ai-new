import { Database, Info } from "lucide-react";
import { overviewViewModel } from "@/lib/demo-data";
import StatusBadge from "@/components/ui/StatusBadge";

export default function DataModeBanner() {
  return <aside className="rounded-xl border border-info/30 bg-info-soft px-5 py-4" aria-label="Data mode">
    <div className="flex items-start gap-3"><Database className="mt-0.5 h-5 w-5 shrink-0 text-info" aria-hidden="true" /><div>
      <div className="flex flex-wrap items-center gap-2"><p className="font-semibold text-primary">Synthetic Capability Demonstration</p><StatusBadge variant="warning">{overviewViewModel.deploymentGate}</StatusBadge></div>
      <p className="mt-1 text-sm text-secondary">Current forecasts, facility readiness, inventory pressure, and operational suggestions are generated from governed synthetic demonstration inputs. Dataset-specific model suitability assessment is required for materially different data.</p>
      <p className="mt-2 flex items-start gap-1.5 text-xs text-secondary"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />No patient-level data is used. Outputs remain advisory and require human review.</p>
    </div></div>
  </aside>;
}
