import type { RiskLevel, NavLink, ScenarioKey } from "./types";

export const PROJECT_TITLE = "DengueOps AI";
export const PROJECT_SUBTITLE =
  "Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South";
export const ICADHI_TRACK = "Track 06: Health Data Analytics & Predictive Systems";
export const CONFERENCE = "IEEE ICADHI 2026";
export const TARGET_CITY = "Dhaka South";

// ─── Risk level palette ────────────────────────────────────────────────────
// Tailwind class strings (bg, text, border)
export const RISK_COLORS: Record<RiskLevel, { bg: string; text: string; border: string; hex: string }> = {
  Low: {
    bg: "bg-emerald-100",
    text: "text-emerald-800",
    border: "border-emerald-300",
    hex: "#10b981",
  },
  Moderate: {
    bg: "bg-yellow-100",
    text: "text-yellow-800",
    border: "border-yellow-300",
    hex: "#f59e0b",
  },
  High: {
    bg: "bg-orange-100",
    text: "text-orange-800",
    border: "border-orange-300",
    hex: "#f97316",
  },
  Critical: {
    bg: "bg-red-100",
    text: "text-red-800",
    border: "border-red-300",
    hex: "#ef4444",
  },
};

// ─── Scenario display ──────────────────────────────────────────────────────
export const SCENARIO_LABELS: Record<ScenarioKey, string> = {
  best_case: "Planning Low",
  expected_case: "Planning Base",
  worst_case: "Planning High",
};

export const SCENARIO_COLORS: Record<ScenarioKey, string> = {
  best_case: "#10b981",
  expected_case: "#0ea5e9",
  worst_case: "#ef4444",
};

// ─── Navigation ───────────────────────────────────────────────────────────
export const NAV_LINKS: NavLink[] = [
  { href: "/dashboard", label: "Overview" },
  { href: "/forecast", label: "New Forecast" },
  { href: "/preparedness", label: "Preparedness" },
  { href: "/validation", label: "Evidence" },
];

export const SECONDARY_NAV_LINKS: NavLink[] = [
  { href: "/methodology", label: "Methodology" },
  { href: "/assumptions", label: "Assumptions" },
  { href: "/ethics", label: "Ethics" },
  { href: "/about", label: "About" },
];

// ─── Chart / brand palette ─────────────────────────────────────────────────
export const BRAND = {
  navy: "var(--text-primary)",
  navyMid: "var(--navy-mid)",
  cyan: "var(--accent)",
  cyanLight: "var(--focus)",
  slate: "var(--text-secondary)",
  slateLight: "var(--surface-muted)",
  white: "var(--text-primary)",
  alertRed: "var(--destructive)",
  alertOrange: "var(--warning)",
  alertYellow: "var(--warning)",
  success: "var(--success)",
};

export const CHART_COLORS = {
  observed: "var(--chart-observed)",
  forecast: "var(--chart-forecast)",
  range: "var(--chart-range)",
  grid: "var(--border-subtle)",
  muted: "var(--text-secondary)",
};

// ─── SDH thresholds (days) ─────────────────────────────────────────────────
export const SDH_CRITICAL_THRESHOLD = 7;
export const SDH_WARNING_THRESHOLD = 14;

// ─── Bed-gap threshold ─────────────────────────────────────────────────────
export const BED_GAP_WARNING = 0;
