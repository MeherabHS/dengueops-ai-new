import StatusBadge from "@/components/ui/StatusBadge";
import type { DashboardRefreshState } from "@/lib/dashboard-view-model";

const STATES: Record<DashboardRefreshState, { label: string; variant: "success" | "info" | "warning" | "destructive" }> = {
  committed: { label: "Committed run", variant: "success" },
  loading_latest_commit: { label: "Loading latest committed run", variant: "info" },
  new_commit_available: { label: "New committed run available", variant: "info" },
  refreshing: { label: "Refreshing committed dashboard", variant: "info" },
  refresh_failed: { label: "Refresh failed — showing last commit", variant: "destructive" },
  stale_commit: { label: "Stale committed run", variant: "warning" },
};

export default function DashboardRefreshStatus({ state }: { state: DashboardRefreshState }) {
  const config = STATES[state];
  return <StatusBadge label={config.label} variant={config.variant} />;
}
