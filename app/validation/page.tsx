import EvidenceTabs from "@/components/evidence/EvidenceTabs";
import RuntimeAssessmentWorkflow from "@/components/validation/RuntimeAssessmentWorkflow";
import StatusBadge from "@/components/ui/StatusBadge";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export default async function ValidationPage({ searchParams }: { searchParams: Promise<{ assessmentId?: string | string[] }> }) {
  const query = await searchParams;
  const supplied = Array.isArray(query.assessmentId) ? null : query.assessmentId;
  const assessmentId = supplied && UUID.test(supplied) ? supplied : null;
  const invalid = supplied != null && assessmentId == null;
  return <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><header className="mb-7 rounded-2xl border border-border bg-surface p-6"><div className="flex flex-wrap gap-2"><StatusBadge label="Governed evidence" variant="info"/><StatusBadge label="Prototype only" variant="warning"/></div><h1 className="mt-4 text-3xl font-bold text-primary">Evidence</h1><p className="mt-2 max-w-3xl text-sm text-secondary">Review uploaded dataset assessment evidence separately from the deterministic bundled benchmark.</p></header>{invalid?<section className="mb-8 rounded-xl border border-destructive/30 bg-destructive/10 p-5"><h2 className="font-semibold text-destructive">Invalid assessment identifier</h2><p className="mt-2 text-sm text-secondary">The assessment query must contain one server-generated UUID. No runtime path was accessed.</p></section>:null}{assessmentId?<section className="mb-10" aria-label="Uploaded Dataset Assessment"><RuntimeAssessmentWorkflow assessmentId={assessmentId}/></section>:null}<section aria-labelledby="bundled-evidence-heading"><p className="text-xs font-semibold uppercase tracking-wider text-warning">Bundled Benchmark Evidence</p><h2 id="bundled-evidence-heading" className="mt-1 mb-5 text-2xl font-bold text-primary">Deterministic synthetic benchmark</h2><EvidenceTabs/></section></div>;
}
