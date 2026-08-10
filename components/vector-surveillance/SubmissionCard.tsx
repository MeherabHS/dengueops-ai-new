"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import Button from "@/components/ui/Button";
import type { VectorAnalysisDispositionV1, VectorGovernanceReason } from "@/lib/community/contracts";

const REASONS: Array<{ value: VectorGovernanceReason; label: string }> = [
  { value: "test_submission", label: "Test submission" },
  { value: "duplicate", label: "Duplicate" },
  { value: "unusable_image", label: "Unusable image" },
  { value: "invalid_location", label: "Invalid location" },
  { value: "irrelevant_content", label: "Irrelevant content" },
  { value: "user_request", label: "User request" },
  { value: "other", label: "Other" },
];

interface SubmissionCardProps {
  submission: {
    submissionId: string;
    receivedAt: string;
    capturedAt: string | null;
    latitude: number | null;
    longitude: number | null;
    locationAccuracyM: number | null;
    contentType: string;
    byteSize: number;
    note: string | null;
    analysisDisposition: VectorAnalysisDispositionV1;
  };
}

function date(value: string): string {
  return new Date(value).toLocaleString("en-BD", { timeZone: "Asia/Dhaka" });
}

function reasonLabel(value: VectorGovernanceReason | null): string {
  return REASONS.find(candidate => candidate.value === value)?.label ?? "Not recorded";
}

export default function SubmissionCard({ submission }: SubmissionCardProps) {
  const router = useRouter();
  const [disposition, setDisposition] = useState(submission.analysisDisposition);
  const [mode, setMode] = useState<"exclude" | "delete" | null>(null);
  const [reason, setReason] = useState<VectorGovernanceReason | "">("");
  const [otherNote, setOtherNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (deleted) return null;

  const close = () => {
    if (busy) return;
    setMode(null);
    setReason("");
    setOtherNote("");
    setConfirmed(false);
    setError(null);
  };

  const mutate = async (method: "PATCH" | "DELETE") => {
    if (!reason || busy || (method === "DELETE" && !confirmed)) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/vector-surveillance/submissions/${submission.submissionId}`, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(method === "PATCH"
          ? { reason, ...(reason === "other" && otherNote.trim() ? { note: otherNote.trim() } : {}) }
          : { reason, confirmation: "delete_permanently" }),
      });
      const payload = await response.json() as { analysisDisposition?: VectorAnalysisDispositionV1; error?: { message?: string } };
      if (!response.ok) throw new Error(payload.error?.message || "The governance action failed.");
      if (method === "DELETE") setDeleted(true);
      else if (payload.analysisDisposition) setDisposition(payload.analysisDisposition);
      close();
      router.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The governance action failed.");
    } finally {
      setBusy(false);
    }
  };

  return <li className="overflow-hidden rounded-xl border border-border">
    {/* eslint-disable-next-line @next/next/no-img-element -- protected runtime images are not statically optimizable */}
    <img src={`/api/vector-surveillance/submissions/${submission.submissionId}/image`} alt="Community vector surveillance submission" className="h-44 w-full bg-muted object-cover" />
    <div className="p-4">
      {disposition.status === "excluded" ? <div className="mb-3 rounded-lg border border-warning/30 bg-warning/10 p-3 text-xs text-secondary">
        <p className="font-semibold text-primary">Excluded from analysis</p>
        <p className="mt-1">Reason: {reasonLabel(disposition.reason)}</p>
        {disposition.note ? <p className="mt-1 break-words">Note: {disposition.note}</p> : null}
      </div> : null}
      <dl className="space-y-1 text-xs text-secondary"><div><dt className="font-semibold text-primary">Submission ID</dt><dd className="break-all">{submission.submissionId}</dd></div><div><dt className="font-semibold text-primary">Received</dt><dd>{date(submission.receivedAt)}</dd></div><div><dt className="font-semibold text-primary">Capture time</dt><dd>{submission.capturedAt ? date(submission.capturedAt) : "Not supplied"}</dd></div><div><dt className="font-semibold text-primary">Location</dt><dd>{submission.latitude !== null && submission.longitude !== null ? `${submission.latitude}, ${submission.longitude}` : "Not available"}</dd></div><div><dt className="font-semibold text-primary">Accuracy</dt><dd>{submission.latitude !== null && submission.longitude !== null && submission.locationAccuracyM !== null ? `±${submission.locationAccuracyM} m` : "Not available"}</dd></div><div><dt className="font-semibold text-primary">File</dt><dd>{submission.contentType} · {submission.byteSize.toLocaleString()} bytes</dd></div><div><dt className="font-semibold text-primary">Processing state</dt><dd>Received</dd></div>{submission.note ? <div><dt className="font-semibold text-primary">Note</dt><dd className="break-words">{submission.note}</dd></div> : null}</dl>

      <div className="mt-4 border-t border-border pt-3">
        <p className="text-xs font-semibold text-primary">Governance actions</p>
        {mode === null ? <div className="mt-2 flex flex-wrap gap-2">
          <Button variant="secondary" disabled={busy || disposition.status === "excluded"} onClick={() => setMode("exclude")}>{disposition.status === "excluded" ? "Excluded from analysis" : "Exclude from analysis"}</Button>
          <Button variant="quiet" className="text-destructive" disabled={busy} onClick={() => setMode("delete")}>Delete permanently</Button>
        </div> : <div className={`mt-3 rounded-lg border p-3 ${mode === "delete" ? "border-destructive/30 bg-destructive/5" : "border-border bg-surface-raised"}`}>
          <p className="text-sm font-semibold text-primary">{mode === "delete" ? "Delete permanently?" : "Exclude from analysis"}</p>
          {mode === "delete" ? <p className="mt-1 text-xs text-secondary">This removes the stored image and submission metadata and cannot be undone.</p> : <p className="mt-1 text-xs text-secondary">The evidence remains available to administrators but is removed from analytical eligibility.</p>}
          <label className="mt-3 block text-xs font-semibold text-primary" htmlFor={`${mode}-reason-${submission.submissionId}`}>Reason</label>
          <select id={`${mode}-reason-${submission.submissionId}`} value={reason} disabled={busy} onChange={event => { setReason(event.target.value as VectorGovernanceReason | ""); setOtherNote(""); }} className="mt-1 min-h-10 w-full rounded-lg border border-border bg-surface px-3 text-sm text-primary">
            <option value="">Select a reason</option>
            {REASONS.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
          {mode === "exclude" && reason === "other" ? <><label className="mt-3 block text-xs font-semibold text-primary" htmlFor={`other-note-${submission.submissionId}`}>Optional note</label><textarea id={`other-note-${submission.submissionId}`} value={otherNote} maxLength={500} disabled={busy} onChange={event => setOtherNote(event.target.value)} className="mt-1 min-h-20 w-full rounded-lg border border-border bg-surface p-2 text-sm text-primary" /></> : null}
          {mode === "delete" ? <label className="mt-3 flex items-start gap-2 text-xs text-secondary"><input type="checkbox" checked={confirmed} disabled={busy} onChange={event => setConfirmed(event.target.checked)} className="mt-0.5" />I understand this deletion cannot be undone.</label> : null}
          {error ? <p className="mt-3 text-xs text-destructive" role="alert">{error}</p> : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant={mode === "delete" ? "danger" : "primary"} disabled={busy || !reason || (mode === "delete" && !confirmed)} onClick={() => void mutate(mode === "delete" ? "DELETE" : "PATCH")}>{busy ? "Saving…" : mode === "delete" ? "Delete permanently" : "Confirm exclusion"}</Button>
            <Button variant="quiet" disabled={busy} onClick={close}>Cancel</Button>
          </div>
        </div>}
      </div>
    </div>
  </li>;
}
