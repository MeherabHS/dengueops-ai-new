"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { Directive } from "@/lib/types";
import { BRAND } from "@/lib/constants";
import dashboardSummaryRaw from "@/data/dashboard_summary.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const policy = (dashboardSummaryRaw as any).formula_policy ?? {};
const thresholdPolicy = policy["OPS.STOCK.THRESHOLDS"]?.parameters ?? {};
const SDH_CRITICAL_THRESHOLD = Number(thresholdPolicy.critical_days ?? 3);
const NS1_WARNING_THRESHOLD = Number(thresholdPolicy.ns1_warning_days ?? 7);
const IVF_WARNING_THRESHOLD = Number(thresholdPolicy.iv_fluid_warning_days ?? 5);

interface Props {
  directives: Directive[];
}

/**
 * Build a short display label from the facility name.
 * Appends the facility_id suffix to guarantee uniqueness across
 * facilities in the same zone (e.g. two Kamrangirchar entries).
 */
function shortLabel(name: string, id: string): string {
  const words = name.split(" ");
  // Take first word + last meaningful word, keep ≤ 16 chars
  const abbrev =
    name.length <= 16
      ? name
      : words.length >= 2
      ? `${words[0]} (${id})`
      : words[0];
  return abbrev;
}

export default function SupplyDepletionChart({ directives }: Props) {
  const data = directives.map((d) => ({
    facilityId: d.facility_id,          // unique key for XAxis dataKey
    label: shortLabel(d.facility_name, d.facility_id),
    ns1: d.sdh_ns1_expected ?? 0,
    iv: d.sdh_iv_fluid_expected ?? 0,
  }));

  const getNs1Color = (v: number) =>
    v <= SDH_CRITICAL_THRESHOLD ? BRAND.alertRed : v <= NS1_WARNING_THRESHOLD ? BRAND.alertOrange : BRAND.cyan;

  return (
    <ResponsiveContainer width="100%" height={300}>
      <BarChart data={data} margin={{ top: 5, right: 16, left: 0, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
        <XAxis
          dataKey="facilityId"
          tickFormatter={(id: string) => data.find((d) => d.facilityId === id)?.label ?? id}
          tick={{ fontSize: 9, fill: BRAND.slate }}
          interval={0}
          angle={-25}
          textAnchor="end"
          height={50}
        />
        <YAxis
          tick={{ fontSize: 11, fill: BRAND.slate }}
          label={{ value: "Days to Depletion", angle: -90, position: "insideLeft", offset: 10, fontSize: 11 }}
        />
        <Tooltip
          formatter={(v, name) => [`${v} days`, name]}
          contentStyle={{ fontSize: 12 }}
        />
        <Legend wrapperStyle={{ fontSize: 12 }} />
        <ReferenceLine y={SDH_CRITICAL_THRESHOLD} stroke={BRAND.alertRed} strokeDasharray="4 3" label={{ value: `Prototype critical (${SDH_CRITICAL_THRESHOLD}d)`, fontSize: 10, fill: BRAND.alertRed }} />
        <ReferenceLine y={NS1_WARNING_THRESHOLD} stroke={BRAND.alertOrange} strokeDasharray="4 3" label={{ value: `NS1 prototype warning (${NS1_WARNING_THRESHOLD}d)`, fontSize: 10, fill: BRAND.alertOrange }} />
        <Bar dataKey="ns1" name="NS1/RDT Kit SDH" radius={[4, 4, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={getNs1Color(d.ns1)} />
          ))}
        </Bar>
        <Bar dataKey="iv" name={`IV Fluid SDH (prototype warning ${IVF_WARNING_THRESHOLD}d)`} fill={BRAND.navyMid} opacity={0.7} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
