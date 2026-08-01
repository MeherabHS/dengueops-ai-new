"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  TrendingUp,
} from "lucide-react";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import ForecastTrendChart from "@/components/overview/ForecastTrendChart";
import OperationalPreparednessTable from "@/components/overview/OperationalPreparednessTable";
import LatestRunCard from "@/components/overview/LatestRunCard";
import DashboardRefreshStatus from "@/components/overview/DashboardRefreshStatus";
import type {OverviewViewModel} from "@/lib/dashboard-view-model";
import { formatDhakaDateTime } from "@/lib/formatters";
import { getLatestDashboard } from "@/lib/runtime/client";

export default function DashboardPage() {
  const [state,setState]=useState<
    |{status:"loading"}
    |{status:"verified";vm:OverviewViewModel}
    |{status:"unavailable";message:string}
  >({status:"loading"});
  const load=async()=>{
    setState({status:"loading"});
    try{
      const latest=await getLatestDashboard();
      if(latest.ok&&latest.sourceType==="uploaded"&&latest.dashboard.latestRun.runId===latest.runId){
        setState({status:"verified",vm:latest.dashboard});
        return;
      }
      setState({status:"unavailable",message:latest.ok?"The latest response did not match the verified current run.":latest.error.message});
    }catch{
      setState({status:"unavailable",message:"The verified current forecast could not be loaded."});
    }
  };
  useEffect(() => {
    let active = true;
    const initialLoad = async () => {
      try {
        const latest = await getLatestDashboard();
        if(!active)return;
        if(latest.ok&&latest.sourceType==="uploaded"&&latest.dashboard.latestRun.runId===latest.runId)setState({status:"verified",vm:latest.dashboard});
        else setState({status:"unavailable",message:latest.ok?"The latest response did not match the verified current run.":latest.error.message});
      } catch {
        if(active)setState({status:"unavailable",message:"The verified current forecast could not be loaded."});
      }
    };
    void initialLoad();
    return () => {
      active = false;
    };
  }, []);
  if(state.status==="loading")return <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><section className="rounded-2xl border border-border bg-surface p-6" aria-live="polite"><StatusBadge label="Verifying" variant="info"/><h1 className="mt-3 text-2xl font-bold text-primary">Verifying current forecast authority</h1><p className="mt-2 text-sm text-secondary">Current forecast cards remain hidden until the latest pointer and exact committed run have been verified.</p></section></main>;
  if(state.status==="unavailable")return <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8"><section className="rounded-2xl border border-warning/30 bg-surface p-6"><StatusBadge label="Authority unavailable" variant="warning"/><h1 className="mt-3 text-2xl font-bold text-primary">Current forecast authority unavailable</h1><p className="mt-2 text-sm text-secondary">{state.message} Bundled benchmark or cached qualification evidence is not shown as current.</p><Button className="mt-5" variant="secondary" onClick={()=>void load()}>Retry verification</Button></section></main>;
  const vm=state.vm;
  const committedAt = formatDhakaDateTime(vm.latestRun.timestamp);
  return (
    <div className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6 lg:px-8">
      <section
        className="rounded-2xl border border-border bg-surface p-5 sm:p-6"
        aria-labelledby="overview-title"
      >
        <div className="mb-4">
          <DashboardRefreshStatus state={vm.latestRun.refreshState} />
        </div>
        <div className="flex flex-col justify-between gap-5 lg:flex-row lg:items-center">
          <div>
            <div className="flex flex-wrap gap-2">
              <StatusBadge label="Dhaka" variant="info" />
              <StatusBadge label="Current governed policy" variant="warning" />
              <StatusBadge label={vm.latestRun.status} variant="success" />
            </div>
            <h1
              id="overview-title"
              className="mt-4 text-3xl font-bold text-primary"
            >
              Overview
            </h1>
            <p className="mt-2 max-w-2xl text-sm text-secondary">
              Latest validated and committed two-week forecast with separate
              preparedness planning indicators.
            </p>
            <p className="mt-2 text-xs text-text-muted">
              Committed {committedAt}
            </p>
          </div>
          <Button href="/forecast/run" className="self-start lg:self-auto">
            Run Forecast <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </section>

      <section
        className="overflow-hidden rounded-2xl border border-border bg-surface"
        aria-labelledby="latest-forecast-title"
      >
        <div className="grid lg:grid-cols-[1.45fr_.55fr]">
          <div className="border-b border-border p-5 sm:p-6 lg:border-b-0 lg:border-r">
            <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
                  Latest forecast
                </p>
                <h2
                  id="latest-forecast-title"
                  className="metric-enter mt-2 text-4xl font-bold text-primary sm:text-5xl"
                >
                  {vm.forecastCases}{" "}
                  <span className="text-base font-medium text-secondary">
                    cases
                  </span>
                </h2>
                <p className="mt-2 text-sm text-secondary">
                  Target {vm.targetPeriod} · {vm.forecastDirection} ·{" "}
                  {vm.sourceType === "uploaded"
                    ? "Uploaded dataset"
                    : "Bundled benchmark"}
                </p>
              </div>
              <div className="rounded-xl border border-success/25 bg-success/10 px-4 py-3 text-right">
                <p className="text-xs text-secondary">
                  Change from latest observation
                </p>
                <p className="metric-enter mt-1 flex items-center justify-end gap-1 text-xl font-bold text-success">
                  <TrendingUp className="h-4 w-4" />
                  {vm.forecastChangeCases >= 0 ? "+" : ""}
                  {vm.forecastChangeCases} cases
                </p>
              </div>
            </div>
            <ForecastTrendChart
              key={vm.latestRun.runId}
              history={vm.history}
              targetPeriod={vm.targetPeriod}
              forecast={vm.forecastCases}
              lower={vm.empiricalRange.lower}
              upper={vm.empiricalRange.upper}
            />
          </div>
          <aside className="flex flex-col justify-between bg-surface-raised p-5 sm:p-6">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">
                {vm.empiricalRange.availabilityStatus === "available"||vm.empiricalRange.availabilityStatus === "governed_available"
                  ? "Calibrated prediction interval"
                  : "Point forecast only"}
              </p>
              {vm.empiricalRange.lower !== null &&
              vm.empiricalRange.upper !== null ? (
                <p className="metric-enter mt-4 text-4xl font-bold text-primary">
                  {vm.empiricalRange.lower}–{vm.empiricalRange.upper}
                </p>
              ) : (
                <p className="mt-4 text-lg font-semibold text-warning">
                  Prediction interval unavailable
                </p>
              )}
              <p className="mt-2 text-sm leading-relaxed text-secondary">
                {vm.empiricalRange.reason ??
                  "Temporally evaluated on synthetic rolling-origin evidence. Historical coverage does not guarantee future coverage."}
              </p>
              <dl className="mt-6 space-y-4 text-sm">
                <div className="flex justify-between gap-4 border-b border-border pb-3">
                  <dt className="text-secondary">Latest observed</dt>
                  <dd className="font-semibold text-primary">
                    {vm.latestObservedCases} cases
                  </dd>
                </div>
                <div className="flex justify-between gap-4 border-b border-border pb-3">
                  <dt className="text-secondary">Raw forecast</dt>
                  <dd className="font-mono text-primary">
                    {vm.forecastRaw.toFixed(3)}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-secondary">Range status</dt>
                  <dd className="text-right text-primary">
                    {vm.empiricalRange.availabilityStatus === "available"||vm.empiricalRange.availabilityStatus === "governed_available"
                      ? "Calibrated interval"
                      : "Unavailable"}
                  </dd>
                </div>
              </dl>
            </div>
            <div className="mt-8 space-y-1 text-xs text-text-muted">
              <p>Model used for this run: <span className="font-semibold text-secondary">{vm.activeModel.label}</span></p>
              {vm.modelUse.scope === "one_run" ? <><p>Decision scope: <span className="font-semibold text-warning">One forecast run</span></p><p>The current governed model assignment is unchanged.</p></> : null}
            </div>
          </aside>
        </div>
      </section>

      {vm.preparedness.availabilityStatus === "available" ? (
        <section aria-labelledby="operational-preparedness-title" className="space-y-4">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-accent">
                Current operational authority
              </p>
              <h2 id="operational-preparedness-title" className="mt-1 text-xl font-bold text-primary">Operational preparedness summary</h2>
              <p className="mt-2 text-sm text-secondary">{vm.preparedness.formulaLabel}. Official capacity references are not live availability or hospital-approved requirements.</p>
            </div>
            <Button href="/preparedness" variant="quiet">
              Open preparedness <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
          <OperationalPreparednessTable rows={vm.preparedness.rows}/>
        </section>
      ) : (
        <section className="rounded-2xl border border-warning/25 bg-warning/10 p-6">
          {vm.preparedness.availabilityStatus==="calculating"?<span className="mb-3 inline-block h-5 w-5 animate-spin rounded-full border-2 border-warning border-t-transparent" aria-hidden="true"/>:null}
          <h2 className="text-xl font-bold text-primary">
            {vm.preparedness.availabilityStatus==="calculating"?"Preparedness calculating":"Preparedness unavailable"}
          </h2>
          <p className="mt-2 text-sm text-secondary">
            {vm.preparedness.reason ?? "No exact-current governed operational preparedness artifact is available."}
          </p>
          <p className="mt-2 text-xs text-text-muted">Bundled and synthetic qualification availability is never substituted for current operational evidence.</p>
        </section>
      )}

      <section
        className="grid gap-5 lg:grid-cols-2"
        aria-label="Alerts and latest committed run"
      >
        <div className="rounded-2xl border border-border bg-surface p-5"><h2 className="font-semibold text-primary">Preparedness evidence boundary</h2><p className="mt-2 text-sm text-secondary">Formula-derived planning estimates use the exact-current forecast and current governed inventory. Current live availability remains Not reported.</p></div>
        <LatestRunCard run={vm.latestRun} />
      </section>
    </div>
  );
}
