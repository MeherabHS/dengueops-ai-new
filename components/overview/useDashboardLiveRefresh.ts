"use client";

import { useEffect, useRef, useState } from "react";
import type { OverviewViewModel } from "@/lib/dashboard-view-model";
import type { LatestDashboardResponse } from "@/lib/runtime/contracts";

export const DASHBOARD_POLL_INTERVAL_MS = 2_500;
export const DASHBOARD_POLL_TIMEOUT_MS = 120_000;
export const DASHBOARD_LATEST_ENDPOINT = "/api/dashboard/latest?deployment=dhaka_south";

export function dashboardHasPendingEvidence(vm: OverviewViewModel | null): boolean {
  return vm !== null && (
    vm.downstreamEvidence.preparednessStatus === "pending"
    || vm.downstreamEvidence.monitoringStatus === "pending"
    || vm.downstreamEvidence.confidenceStatus === "pending"
  );
}

export function useDashboardLiveRefresh(
  vm: OverviewViewModel | null,
  acceptVerified: (dashboard: OverviewViewModel) => void,
): { timedOut: boolean } {
  const [timedOutRunId, setTimedOutRunId] = useState<string | null>(null);
  const deadline = useRef<{ runId: string; value: number } | null>(null);

  useEffect(() => {
    if (vm === null || !dashboardHasPendingEvidence(vm)) {
      deadline.current = null;
      return;
    }
    const runId = vm.latestRun.runId;
    if (deadline.current?.runId !== runId) {
      deadline.current = { runId, value: Date.now() + DASHBOARD_POLL_TIMEOUT_MS };
    }
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let controller: AbortController | null = null;

    const schedule = () => {
      if (!active) return;
      const remaining = (deadline.current?.value ?? 0) - Date.now();
      if (remaining <= 0) {
        setTimedOutRunId(runId);
        return;
      }
      timer = setTimeout(() => void refresh(), Math.min(DASHBOARD_POLL_INTERVAL_MS, remaining));
    };
    const refresh = async () => {
      if (!active) return;
      controller = new AbortController();
      try {
        const response = await fetch(DASHBOARD_LATEST_ENDPOINT, {
          method: "GET",
          cache: "no-store",
          signal: controller.signal,
          headers: { Accept: "application/json" },
        });
        if (!active) return;
        if (response.status === 401 || response.status === 403) return;
        if (response.ok) {
          const latest = await response.json() as LatestDashboardResponse;
          if (latest.ok && latest.sourceType === "uploaded" && latest.dashboard.latestRun.runId === latest.runId) {
            acceptVerified(latest.dashboard);
            if (!dashboardHasPendingEvidence(latest.dashboard)) return;
          }
        }
      } catch (error) {
        if (!active || (error instanceof DOMException && error.name === "AbortError")) return;
      }
      schedule();
    };
    schedule();
    return () => {
      active = false;
      if (timer !== null) clearTimeout(timer);
      controller?.abort();
    };
  }, [acceptVerified, vm]);

  return { timedOut: vm !== null && timedOutRunId === vm.latestRun.runId };
}
