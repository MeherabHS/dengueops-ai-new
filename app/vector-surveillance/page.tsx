import Link from "next/link";

export default function VectorSurveillancePage() {
  return <div className="mx-auto max-w-6xl space-y-6 px-4 py-10 sm:px-6 lg:px-8">
    <header className="rounded-2xl border border-border bg-surface p-6">
      <p className="text-xs font-semibold uppercase tracking-wider text-accent">Super User evidence intake</p>
      <h1 className="mt-2 text-3xl font-bold text-primary">Vector Surveillance</h1>
      <p className="mt-2 max-w-3xl text-sm text-secondary">Review Community-submitted vector images saved as intake evidence. Image analysis and classification are planned capabilities and are not performed in this phase.</p>
    </header>
    <section className="grid gap-4 md:grid-cols-2">
      <div className="rounded-2xl border border-border bg-surface p-6"><h2 className="text-xl font-semibold text-primary">Saved datasets / images</h2><p className="mt-2 text-sm text-secondary">Browse immutable Community image submissions and their bounded intake metadata.</p><Link className="mt-5 inline-flex rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-white" href="/vector-surveillance/saved-datasets-images">Open saved datasets / images</Link></div>
      <div className="rounded-2xl border border-border bg-surface p-6"><h2 className="text-xl font-semibold text-primary">Vector analysis</h2><p className="mt-2 text-sm text-secondary">Planned. No species detection, classification, or risk scoring is active.</p></div>
    </section>
  </div>;
}
