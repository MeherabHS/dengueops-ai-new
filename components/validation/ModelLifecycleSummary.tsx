"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import StatusBadge from "@/components/ui/StatusBadge";
import { getModelLifecycle } from "@/lib/runtime/client";
import type { ModelLifecycleResponse } from "@/lib/runtime/contracts";

export default function ModelLifecycleSummary() {
  const [state, setState] = useState<ModelLifecycleResponse | null>(null);

  const refresh = useCallback(() => {
    setState(null);
    void getModelLifecycle().then(setState);
  }, []);

  useEffect(() => {
    let live = true;
    getModelLifecycle().then((value) => {
      if (live) setState(value);
    });
    return () => {
      live = false;
    };
  }, []);

  if (!state) {
    return (
      <section className="mb-10 rounded-xl border border-border bg-surface p-5" aria-label="Current runtime authority">
        <p className="text-sm text-secondary">Verifying current model authority…</p>
      </section>
    );
  }

  if (!state.ok) {
    return (
      <section className="mb-10 rounded-xl border border-destructive/30 bg-destructive/10 p-5" aria-label="Current runtime authority unavailable">
        <StatusBadge label="Current model authority unavailable" variant="destructive" />
        <h2 className="mt-3 text-xl font-bold text-primary">Current runtime authority</h2>
        <p className="mt-2 text-sm text-secondary">
          The current governed assignment could not be verified. Historical benchmark evidence remains available
          separately and is not current operational evidence.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="button" onClick={refresh} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-semibold text-primary">
            Refresh evidence
          </button>
          <Link href="/forecast" className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-semibold text-primary">
            Return to model assignment
          </Link>
          <details className="w-full rounded-lg border border-border bg-surface p-3 text-xs text-secondary">
            <summary className="cursor-pointer font-semibold text-primary">Technical evidence</summary>
            <p className="mt-2">{state.error.message}</p>
            <p className="mt-1 font-mono">{state.error.code}</p>
          </details>
        </div>
      </section>
    );
  }

  const authority = state.authority;
  return (
    <section className="mb-10 rounded-2xl border border-border bg-surface p-6" aria-labelledby="lifecycle-heading">
      <div className="flex flex-wrap gap-2">
        <StatusBadge label="Verified committed assignment" variant="success" />
        <StatusBadge label="Human governed" variant="info" />
        <StatusBadge label="Automatic action disabled" variant="warning" />
      </div>
      <h2 id="lifecycle-heading" className="mt-3 text-2xl font-bold text-primary">Current runtime authority</h2>
      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-border bg-background p-4">
          <p className="text-xs text-text-muted">Current governed model</p>
          <p className="mt-1 font-semibold text-primary">{authority.modelLabel}</p>
        </div>
        <div className="rounded-xl border border-border bg-background p-4">
          <p className="text-xs text-text-muted">Authority</p>
          <p className="mt-1 text-sm font-semibold text-primary">{authority.authorityLabel}</p>
        </div>
      </div>
      <p className="mt-4 text-sm text-secondary">
        This evidence is read-only. Material worsening, statistical sufficiency, and model qualification remain
        outside the governed current-authority claim.
      </p>
      <details className="mt-4 rounded-lg border border-border bg-background p-3 text-xs text-secondary">
        <summary className="cursor-pointer font-semibold text-primary">Technical evidence</summary>
        <dl className="mt-3 grid gap-2 sm:grid-cols-2">
          <div><dt>Candidate ID</dt><dd className="font-mono">{authority.modelId}</dd></div>
          <div><dt>Estimator class</dt><dd className="font-mono">{authority.modelFamily}</dd></div>
          <div><dt>Assignment ID</dt><dd className="break-all font-mono">{authority.assignmentId}</dd></div>
          <div><dt>Authority source</dt><dd className="font-mono">{authority.authoritySource}</dd></div>
          <div><dt>Lifecycle policy</dt><dd className="font-mono">{authority.lifecyclePolicyId} · {authority.lifecyclePolicyVersion}</dd></div>
          <div><dt>Parameter SHA-256</dt><dd className="break-all font-mono">{authority.parameterSha256}</dd></div>
          <div><dt>Registry SHA-256</dt><dd className="break-all font-mono">{authority.candidateRegistrySha256}</dd></div>
          <div><dt>Pointer SHA-256</dt><dd className="break-all font-mono">{authority.authoritySnapshotSha256}</dd></div>
        </dl>
      </details>
    </section>
  );
}
