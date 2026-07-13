import EvidenceTabs from "@/components/evidence/EvidenceTabs";
import StatusBadge from "@/components/ui/StatusBadge";

export default function ValidationPage() {
  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><header className="mb-7 rounded-2xl border border-border bg-surface p-6"><div className="flex flex-wrap gap-2"><StatusBadge label="Synthetic capability demonstration" variant="info"/><StatusBadge label="Benchmark only" variant="warning"/></div><h1 className="mt-4 text-3xl font-bold text-primary">Evidence</h1><p className="mt-2 max-w-3xl text-sm text-secondary">Review model suitability, temporal forecast evaluation, active-model diagnostics, provenance, and concise limitations for the latest committed run.</p></header><EvidenceTabs/></div>;
}
