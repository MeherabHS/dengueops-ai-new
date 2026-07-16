"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ApprovalPanel from "@/components/forecast/ApprovalPanel";
import ModelSuitabilitySummary from "@/components/forecast/ModelSuitabilitySummary";
import ProcessingState from "@/components/forecast/ProcessingState";
import Button from "@/components/ui/Button";
import EmptyState from "@/components/ui/EmptyState";
import {
  getDatasetAssessment,
  getLatestDashboard,
  getRuntimeJob,
  recordAssessmentDecision,
  startApprovedForecast,
} from "@/lib/runtime/client";
import type {
  DatasetAssessmentResultSuccess,
  DecisionChoice,
  DecisionResultSuccess,
} from "@/lib/runtime/contracts";

export default function RuntimeAssessmentWorkflow({ assessmentId }: { assessmentId: string }) {
  const mounted = useRef(true);
  const [assessment, setAssessment] = useState<DatasetAssessmentResultSuccess | null>(null);
  const [decision, setDecision] = useState<DecisionResultSuccess | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "queued" | "running" | "committing" | "failed">("loading");
  const [stage, setStage] = useState<string>();
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const response = await getDatasetAssessment(assessmentId);
    if (!response.ok) throw new Error(response.error.message);
    if (mounted.current) {
      setAssessment(response);
      setStatus("ready");
      setError(null);
    }
    return response;
  }, [assessmentId]);

  useEffect(() => {
    mounted.current = true;
    void refresh().catch((reason: unknown) => {
      if (mounted.current) {
        setStatus("failed");
        setError(reason instanceof Error ? reason.message : "The committed assessment could not be verified.");
      }
    });
    return () => { mounted.current = false; };
  }, [refresh]);

  const recordDecision = async (choice: DecisionChoice, reason: string) => {
    if (!assessment) return;
    setStatus("queued");
    setError(null);
    try {
      const response = await recordAssessmentDecision(assessmentId, {
        decision: choice,
        reason,
        expectedAssessmentSummarySha256: assessment.integrity.assessmentSummarySha256,
      });
      if (!response.ok) throw new Error(response.error.message);
      if (mounted.current) {
        setDecision(response);
        setStatus("ready");
      }
      await refresh();
    } catch (reasonValue) {
      if (mounted.current) {
        setStatus("failed");
        setError(reasonValue instanceof Error ? reasonValue.message : "The trusted-internal decision could not be recorded.");
      }
    }
  };

  const runApprovedForecast = async () => {
    if (!assessment) return;
    const recorded = decision ?? assessment.workflow.decision;
    if (!recorded?.forecastAuthorized || recorded.authorizationStatus !== "available") return;
    setStatus("queued");
    setError(null);
    try {
      const started = await startApprovedForecast(recorded.decisionId, {
        expectedDecisionCommitSha256: recorded.decisionCommitSha256,
      });
      if (!started.ok) throw new Error(started.error.message);
      let delay = 2000;
      while (mounted.current) {
        const job = await getRuntimeJob(started.jobId);
        if (!job.ok) throw new Error(job.error.message);
        setStage(job.progress);
        if (job.status === "queued" || job.status === "running" || job.status === "committing") setStatus(job.status);
        if (job.status === "completed") {
          if (job.jobKind !== "approved_forecast" || job.committedRunId !== started.runId) throw new Error("The approved worker completed without the expected immutable run.");
          const latest = await getLatestDashboard("dhaka_south");
          if (!latest.ok || latest.runId !== started.runId || latest.dashboard.latestRun.runId !== started.runId) throw new Error(latest.ok ? "The committed dashboard did not match the selected-model run." : latest.error.message);
          sessionStorage.setItem("dengueops-latest-dashboard", JSON.stringify({ runId: latest.runId, dashboard: latest.dashboard }));
          setDecision(null);
          await refresh();
          setStage("completed");
          return;
        }
        if (job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") throw new Error(job.error?.message ?? `The approved forecast ended with ${job.status}.`);
        await new Promise((resolve) => window.setTimeout(resolve, delay));
        delay = Math.min(10000, Math.round(delay * 1.35));
      }
    } catch (reasonValue) {
      if (mounted.current) {
        setStatus("failed");
        setError(reasonValue instanceof Error ? reasonValue.message : "The selected-model forecast failed.");
      }
    }
  };

  if (status === "loading") return <section className="rounded-xl border border-border-subtle bg-surface p-5"><p className="text-sm text-ink-muted">Loading and verifying committed uploaded assessment evidence…</p></section>;
  if (!assessment) return <EmptyState title="Uploaded assessment unavailable" description={error ?? "The assessment is missing, invalid, incomplete, or failed integrity validation."} />;
  return <section className="space-y-5" aria-labelledby="uploaded-assessment-heading">
    <div><p className="text-xs font-semibold uppercase tracking-wider text-accent">Uploaded Dataset Assessment</p><h2 id="uploaded-assessment-heading" className="mt-1 text-2xl font-bold text-primary">Governed multi-model assessment</h2><p className="mt-2 max-w-4xl text-sm text-secondary">This evidence belongs only to assessment {assessmentId}. It is separate from the bundled benchmark, empirical-range calibration, outcome monitoring, and preparedness evidence.</p></div>
    {error ? <div className="rounded-xl border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">{error}</div> : null}
    <ModelSuitabilitySummary assessment={assessment} />
    <ApprovalPanel assessment={assessment} decision={decision} workflowDecision={assessment.workflow.decision} busy={["queued","running","committing"].includes(status)} onDecision={(choice, reason) => void recordDecision(choice, reason)} onForecast={() => void runApprovedForecast()} />
    {["queued","running","committing"].includes(status) ? <ProcessingState status={status} stage={stage} workflow="assess_dataset" /> : null}
    {assessment.workflow.decision?.forecastStatus === "committed" ? <Button href="/dashboard">Open committed forecast overview</Button> : null}
  </section>;
}
