import { listSubmissions } from "@/lib/community/vector-storage";

export const dynamic = "force-dynamic";

function coordinate(value: number): string {
  return String(value);
}

export default async function SavedDatasetsImagesPage() {
  const { submissions } = await listSubmissions(25);
  return <div className="mx-auto max-w-6xl space-y-6 px-4 py-10 sm:px-6 lg:px-8">
    <header><p className="text-xs font-semibold uppercase tracking-wider text-accent">Vector Surveillance</p><h1 className="mt-2 text-3xl font-bold text-primary">Saved datasets / images</h1></header>
    <section className="rounded-2xl border border-border bg-surface p-6">
      <h2 className="text-xl font-semibold text-primary">Images</h2>
      {submissions.length === 0 ? <p className="mt-4 text-sm text-secondary">No Community image submissions have been received yet.</p> : <ul className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{submissions.map(item => <li key={item.submissionId} className="overflow-hidden rounded-xl border border-border">
        {/* eslint-disable-next-line @next/next/no-img-element -- protected runtime images are not statically optimizable */}
        <img src={`/api/vector-surveillance/submissions/${item.submissionId}/image`} alt="Community vector surveillance submission" className="h-44 w-full bg-muted object-cover" />
        <dl className="space-y-1 p-4 text-xs text-secondary"><div><dt className="font-semibold text-primary">Submission ID</dt><dd className="break-all">{item.submissionId}</dd></div><div><dt className="font-semibold text-primary">Received</dt><dd>{new Date(item.receivedAt).toLocaleString("en-BD")}</dd></div><div><dt className="font-semibold text-primary">Capture time</dt><dd>{item.capturedAt ? new Date(item.capturedAt).toLocaleString("en-BD") : "Not supplied"}</dd></div><div><dt className="font-semibold text-primary">Location</dt><dd>{item.latitude !== null && item.longitude !== null ? `${coordinate(item.latitude)}, ${coordinate(item.longitude)}` : "Not available"}</dd></div><div><dt className="font-semibold text-primary">Accuracy</dt><dd>{item.latitude !== null && item.longitude !== null && item.locationAccuracyM !== null ? `±${item.locationAccuracyM} m` : "Not available"}</dd></div><div><dt className="font-semibold text-primary">File</dt><dd>{item.contentType} · {item.byteSize.toLocaleString()} bytes</dd></div><div><dt className="font-semibold text-primary">Processing state</dt><dd>Received</dd></div>{item.note ? <div><dt className="font-semibold text-primary">Note</dt><dd className="break-words">{item.note}</dd></div> : null}</dl>
      </li>)}</ul>}
    </section>
    <section className="rounded-2xl border border-border bg-surface p-6"><h2 className="text-xl font-semibold text-primary">Datasets</h2><p className="mt-2 text-sm text-secondary">Reserved for a future governed dataset-intake phase. Dataset upload is not available.</p></section>
  </div>;
}
