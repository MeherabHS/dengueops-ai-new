"use client";

import { useEffect, useState } from "react";
import {
  ArrowRight,
  BedDouble,
  Droplets,
  PackageSearch,
  ShieldAlert,
  TrendingUp,
} from "lucide-react";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import ForecastTrendChart from "@/components/overview/ForecastTrendChart";
import PreparednessCountCard from "@/components/overview/PreparednessCountCard";
import FacilityAttentionList from "@/components/overview/FacilityAttentionList";
import AlertList from "@/components/overview/AlertList";
import LatestRunCard from "@/components/overview/LatestRunCard";
import DashboardRefreshStatus from "@/components/overview/DashboardRefreshStatus";
import { bundledOverviewViewModel } from "@/lib/dashboard-view-model";
import { getLatestDashboard } from "@/lib/runtime/client";

export default function DashboardPage() {
  const [vm, setVm] = useState(bundledOverviewViewModel);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const cached = sessionStorage.getItem("dengueops-latest-dashboard");
        if (cached) {
          const value = JSON.parse(cached) as {
            runId?: string;
            dashboard?: typeof bundledOverviewViewModel;
          };
          if (
            active &&
            value.runId &&
            value.dashboard?.latestRun.runId === value.runId
          )
            setVm(value.dashboard);
          sessionStorage.removeItem("dengueops-latest-dashboard");
        }
        const latest = await getLatestDashboard();
        if (
          active &&
          latest.ok &&
          latest.dashboard.latestRun.runId === latest.runId
        )
          setVm(latest.dashboard);
      } catch {
        /* preserve the previous committed view */
      }
    };
    void load();
    return () => {
      active = false;
    };
  }, []);
  const committedAt = new Date(vm.latestRun.timestamp).toLocaleString();
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
              <StatusBadge label={vm.deployment.mode} variant="info" />
              <StatusBadge label={vm.deployment.gate} variant="warning" />
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
          <Button href="/forecast" className="self-start lg:self-auto">
            Start New Forecast Run <ArrowRight className="h-4 w-4" />
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
                {vm.empiricalRange.availabilityStatus === "available"
                  ? "Empirical forecast range"
                  : "Empirical range unavailable"}
              </p>
              {vm.empiricalRange.lower !== null &&
              vm.empiricalRange.upper !== null ? (
                <p className="metric-enter mt-4 text-4xl font-bold text-primary">
                  {vm.empiricalRange.lower}–{vm.empiricalRange.upper}
                </p>
              ) : (
                <p className="mt-4 text-lg font-semibold text-warning">
                  Pending calibration
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
                    {vm.empiricalRange.availabilityStatus === "available"
                      ? "Empirical evidence"
                      : "Unavailable"}
                  </dd>
                </div>
              </dl>
            </div>
            <div className="mt-8 space-y-1 text-xs text-text-muted">
              <p>Model used for this run: <span className="font-semibold text-secondary">{vm.activeModel.label}</span></p>
              {vm.modelUse.scope === "one_run" ? <><p>Decision scope: <span className="font-semibold text-warning">One forecast run</span></p><p>Deployment-wide Random Forest model unchanged.</p></> : null}
            </div>
          </aside>
        </div>
      </section>

      {vm.preparedness.availabilityStatus === "available" ? (
        <section aria-labelledby="preparedness-count-title">
          <div className="mb-4 flex items-end justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-accent">
                Planning Base
              </p>
              <h2
                id="preparedness-count-title"
                className="mt-1 text-xl font-bold text-primary"
              >
                Preparedness count indicators
              </h2>
            </div>
            <Button href="/preparedness" variant="quiet">
              Open preparedness <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <PreparednessCountCard
              label="Bed-deficit facilities"
              affected={vm.preparedness.bedDeficitFacilities}
              total={vm.preparedness.totalFacilities}
              note="Projected demand exceeds configured dengue beds."
              icon={<BedDouble className="h-4 w-4" />}
            />
            <PreparednessCountCard
              label="NS1/RDT stock horizon ≤14 days"
              affected={vm.preparedness.ns1StockHorizonFacilities}
              total={vm.preparedness.totalFacilities}
              note="Stock-horizon indicator; not necessarily a critical alert."
              icon={<PackageSearch className="h-4 w-4" />}
            />
            <PreparednessCountCard
              label="IV-fluid stock horizon ≤14 days"
              affected={vm.preparedness.ivFluidStockHorizonFacilities}
              total={vm.preparedness.totalFacilities}
              note="Stock-horizon indicator; not necessarily a critical alert."
              icon={<Droplets className="h-4 w-4" />}
            />
            <PreparednessCountCard
              label="Facilities requiring critical review"
              affected={vm.preparedness.criticalReviewFacilities}
              total={vm.preparedness.totalFacilities}
              note="Counted separately from stock-horizon review."
              icon={<ShieldAlert className="h-4 w-4" />}
            />
          </div>
        </section>
      ) : (
        <section className="rounded-2xl border border-warning/25 bg-warning/10 p-6">
          <h2 className="text-xl font-bold text-primary">
            Preparedness unavailable
          </h2>
          <p className="mt-2 text-sm text-secondary">
            No governed runtime planning-scenario policy is currently approved.
            No scenarios, facilities, inventory alerts, or directives were
            generated.
          </p>
        </section>
      )}

      {vm.preparedness.availabilityStatus === "available" ? (
        <FacilityAttentionList facilities={vm.facilitiesRequiringAttention} />
      ) : null}

      <section
        className="grid gap-5 lg:grid-cols-2"
        aria-label="Alerts and latest committed run"
      >
        {vm.preparedness.availabilityStatus === "available" ? (
          <AlertList alerts={vm.alerts} />
        ) : (
          <div className="rounded-2xl border border-border bg-surface p-5">
            <h2 className="font-semibold text-primary">
              No runtime preparedness alerts
            </h2>
            <p className="mt-2 text-sm text-secondary">
              Preparedness generation was not authorized for this uploaded
              forecast.
            </p>
          </div>
        )}
        <LatestRunCard run={vm.latestRun} />
      </section>
    </div>
  );
}
