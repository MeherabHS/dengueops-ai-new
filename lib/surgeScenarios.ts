// ─── Surge Scenario Simulation Layer ─────────────────────────────────────────
// These are deterministic what-if overlays applied client-side to base zone
// data. They do NOT retrain the forecasting model or modify JSON files.

import chartDataRaw from "@/data/chart_data.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const cd = chartDataRaw as any;
const formulaPolicy = cd?.formula_policy ?? {};
const priorityPolicy = formulaPolicy["OPS.PRIORITY.CATEGORIES"]?.parameters ?? {};

export type SurgeKey =
  | "normal"
  | "old_dhaka_surge"
  | "kamrangirchar_surge"
  | "jatrabari_surge"
  | "city_wide_critical";

export interface SurgeScenarioMeta {
  key: SurgeKey;
  label: string;
  short: string;
  color: string;
  bgColor: string;
  borderColor: string;
  explanation: string;
  affectedZones: string[];
  operationalImplication: string;
}

export interface ZoneSurgeData {
  zone_name: string;
  baseline_priority: number;
  baseline_cases: number;
  baseline_risk: string;
  adjusted_priority: number;
  adjusted_cases: number;
  adjusted_risk: string;
  modifier: number;
}

// ─── Scenario metadata ────────────────────────────────────────────────────────

export const SURGE_SCENARIOS: SurgeScenarioMeta[] = [
  {
    key: "normal",
    label: "Normal Monitoring",
    short: "Normal",
    color: "text-slate-700",
    bgColor: "bg-slate-100",
    borderColor: "border-slate-300",
    explanation:
      "Baseline expected-case projection. No additional surge modifier applied. Use forecast expected-case values.",
    affectedZones: [],
    operationalImplication: "Continue routine surveillance and standard readiness posture.",
  },
  {
    key: "old_dhaka_surge",
    label: "Old Dhaka Surge",
    short: "Old Dhaka",
    color: "text-amber-700",
    bgColor: "bg-amber-50",
    borderColor: "border-amber-300",
    explanation:
      "Dense older urban area with high referral pressure from informal settlements. Mitford/Old Dhaka priority increases 25%; Lalbagh/Hazaribagh increases 10% due to proximity pressure.",
    affectedZones: ["Mitford / Old Dhaka", "Lalbagh / Hazaribagh"],
    operationalImplication:
      "Pre-position NS1/RDT stock in Old Dhaka zone facilities. Alert referral hospitals. Intensify vector-control in dense residential streets.",
  },
  {
    key: "kamrangirchar_surge",
    label: "Kamrangirchar Surge",
    short: "Kamrangirchar",
    color: "text-orange-700",
    bgColor: "bg-orange-50",
    borderColor: "border-orange-300",
    explanation:
      "High-density, high-vulnerability informal settlement with limited facility access. Priority increases 30%; expected bed gap widens significantly.",
    affectedZones: ["Kamrangirchar"],
    operationalImplication:
      "Activate contingency dengue beds. Issue early community advisory. Deploy mobile NS1/RDT teams. Escalate SDH review.",
  },
  {
    key: "jatrabari_surge",
    label: "Jatrabari Mobility Surge",
    short: "Jatrabari",
    color: "text-violet-700",
    bgColor: "bg-violet-50",
    borderColor: "border-violet-300",
    explanation:
      "Mobility corridor and transport-linked exposure increases case import risk. Jatrabari/Sayedabad priority increases 25%; Lalbagh increases 10% due to adjacent spillover.",
    affectedZones: ["Jatrabari / Sayedabad", "Lalbagh / Hazaribagh"],
    operationalImplication:
      "Focus vector-control on transit hubs and markets. Increase NS1 sampling at local health posts. Watch facility SDH closely.",
  },
  {
    key: "city_wide_critical",
    label: "City-Wide Critical Surge",
    short: "City-Wide Critical",
    color: "text-red-700",
    bgColor: "bg-red-50",
    borderColor: "border-red-300",
    explanation:
      "Severe simultaneous pressure across all zones. All zones increase 25–40%. Bed pressure peaks; SDH compresses across multiple facilities.",
    affectedZones: [
      "Kamrangirchar",
      "Mitford / Old Dhaka",
      "Dhanmondi",
      "Jatrabari / Sayedabad",
      "Lalbagh / Hazaribagh",
    ],
    operationalImplication:
      "Activate city-level dengue surge protocol. Alert all facilities. Issue public advisory. Escalate supply logistics. Request additional emergency stock.",
  },
];

// ─── Scenario config: zone modifiers + total forecast multiplier ──────────────
//
// Priority score (0–100) categories:
//   0–25  = Routine
//   26–50 = Moderate
//   51–75 = High
//   76+   = Critical
//
// scenario_priority_score = base_priority_score × zone_modifier × total_forecast_multiplier
// Capped at 100 for display.

interface ScenarioConfig {
  totalMultiplier: number;                        // Multiplier on total city forecast
  zoneModifiers: Partial<Record<string, number>>; // Per-zone priority multipliers
}

const SCENARIO_CONFIG: Record<SurgeKey, ScenarioConfig> = {
  normal: {
    totalMultiplier: 1.0,
    zoneModifiers: {},
  },
  old_dhaka_surge: {
    totalMultiplier: 1.05,
    zoneModifiers: {
      "Mitford / Old Dhaka":  1.30,
      "Lalbagh / Hazaribagh": 1.10,
    },
  },
  kamrangirchar_surge: {
    totalMultiplier: 1.05,
    zoneModifiers: {
      Kamrangirchar: 1.35,
    },
  },
  jatrabari_surge: {
    totalMultiplier: 1.05,
    zoneModifiers: {
      "Jatrabari / Sayedabad": 1.35,
      "Lalbagh / Hazaribagh":  1.10,
    },
  },
  city_wide_critical: {
    totalMultiplier: 1.30,
    zoneModifiers: {
      Kamrangirchar:           1.15,
      "Mitford / Old Dhaka":   1.15,
      Dhanmondi:               1.15,
      "Jatrabari / Sayedabad": 1.15,
      "Lalbagh / Hazaribagh":  1.15,
    },
  },
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

/** Derive priority category from score (0–100). */
function deriveRisk(score: number): string {
  if (score > Number(priorityPolicy.high_max ?? 75)) return "Highest simulated planning tier";
  if (score > Number(priorityPolicy.moderate_max ?? 50)) return "High simulated planning tier";
  if (score > Number(priorityPolicy.routine_max ?? 25)) return "Moderate simulated planning tier";
  return "Routine simulated planning tier";
}

// ─── Base zone data from chart_data.json ─────────────────────────────────────

export interface BaseZone {
  zone_name: string;
  priority_score: number;
  allocated_cases: number;
  risk_category: string;
}

export const BASE_ZONES: BaseZone[] = (cd?.zone_priority ?? []).map(
  (z: BaseZone) => ({
    zone_name:      z.zone_name,
    priority_score: Number(z.priority_score),
    allocated_cases: Number(z.allocated_cases),
    risk_category:  z.risk_category,
  })
);

// ─── Apply surge modifier ─────────────────────────────────────────────────────

export function applySurge(surgeKey: SurgeKey): ZoneSurgeData[] {
  const cfg = SCENARIO_CONFIG[surgeKey];
  const { totalMultiplier, zoneModifiers } = cfg;

  const result: ZoneSurgeData[] = BASE_ZONES.map((z) => {
    const zoneMod    = zoneModifiers[z.zone_name] ?? 1.0;
    // Combined multiplier for this zone's priority
    const combined   = zoneMod * totalMultiplier;
    const adjPriority = Math.min(100, Math.round(z.priority_score * combined));
    // Allocated cases scale with total forecast multiplier only (city-level)
    const adjCases    = parseFloat((z.allocated_cases * totalMultiplier).toFixed(1));

    return {
      zone_name:         z.zone_name,
      baseline_priority: z.priority_score,
      baseline_cases:    z.allocated_cases,
      baseline_risk:     z.risk_category,
      adjusted_priority: adjPriority,
      adjusted_cases:    adjCases,
      adjusted_risk:     deriveRisk(adjPriority),
      modifier:          zoneMod,
    };
  });

  // Dev-only diagnostic table
  if (process.env.NODE_ENV === "development") {
    console.table(
      result.map((r) => ({
        zone_name:              r.zone_name,
        base_priority_score:    r.baseline_priority,
        scenario_priority_score: r.adjusted_priority,
        category:               r.adjusted_risk,
      }))
    );
  }

  return result;
}

export function getSurgeMeta(key: SurgeKey): SurgeScenarioMeta {
  return SURGE_SCENARIOS.find((s) => s.key === key) ?? SURGE_SCENARIOS[0];
}
