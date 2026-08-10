import { listSubmissions } from "@/lib/community/vector-storage";
import SubmissionCard from "@/components/vector-surveillance/SubmissionCard";

export const dynamic = "force-dynamic";

export default async function SavedDatasetsImagesPage() {
  const { submissions } = await listSubmissions(25);
  return <div className="mx-auto max-w-6xl space-y-6 px-4 py-10 sm:px-6 lg:px-8">
    <header><p className="text-xs font-semibold uppercase tracking-wider text-accent">Vector Surveillance</p><h1 className="mt-2 text-3xl font-bold text-primary">Saved datasets / images</h1></header>
    <section className="rounded-2xl border border-border bg-surface p-6">
      <h2 className="text-xl font-semibold text-primary">Images</h2>
      {submissions.length === 0 ? <p className="mt-4 text-sm text-secondary">No Community image submissions have been received yet.</p> : <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{submissions.map(item => <SubmissionCard key={item.submissionId} submission={{
        submissionId: item.submissionId, receivedAt: item.receivedAt, capturedAt: item.capturedAt,
        latitude: item.latitude, longitude: item.longitude, locationAccuracyM: item.locationAccuracyM,
        contentType: item.contentType, byteSize: item.byteSize, note: item.note,
        analysisDisposition: item.analysisDisposition,
      }} />)}</ul>}
    </section>
    <section className="rounded-2xl border border-border bg-surface p-6"><h2 className="text-xl font-semibold text-primary">Datasets</h2><p className="mt-2 text-sm text-secondary">Reserved for a future governed dataset-intake phase. Dataset upload is not available.</p></section>
  </div>;
}
