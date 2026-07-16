import StatusPill from "@/components/ui/StatusPill";
import type { Directive } from "@/lib/types";
import { getSdhSeverity } from "@/lib/risk-utils";

interface Props {
  directives: Directive[];
}

function priorityCategoryVariant(cat: string): "critical" | "warning" | "info" | "ok" {
  if (cat === "Critical") return "critical";
  if (cat === "High") return "warning";
  if (cat === "Moderate") return "info";
  return "ok";
}

function bedGapVariant(gap: number): "critical" | "warning" | "ok" {
  if (gap > 5) return "critical";
  if (gap > 0) return "warning";
  return "ok";
}

function AnchorBadge({ anchorType }: { anchorType: string }) {
  const isReal = anchorType === "real_public_hospital_anchor";
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold whitespace-nowrap ${
        isReal
          ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
          : "bg-slate-100 text-slate-500 border border-slate-200"
      }`}
    >
      {isReal ? (
        <>
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
          Real public anchor
        </>
      ) : (
        <>
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-slate-400" />
          Synthetic local unit
        </>
      )}
    </span>
  );
}

export default function FacilityReadinessTable({ directives }: Props) {
  const sorted = [...directives].sort((a, b) => b.priority_score - a.priority_score);

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 shadow-sm">
      <table className="min-w-full text-xs divide-y divide-slate-100">
        <thead className="bg-slate-50">
          <tr>
            {[
              "Facility",
              "Zone",
              "Anchor Type",
              "Gen. Beds",
              "Demo Dengue Beds",
              "Proj. Bed Load",
              "Exp. Bed Gap",
              "NS1 SDH",
              "IVF SDH",
              "Priority",
              "Key Recommendation",
            ].map((h) => (
              <th
                key={h}
                className="px-3 py-2.5 text-left font-semibold text-slate-500 uppercase tracking-wide text-[10px] whitespace-nowrap"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-50 bg-white">
          {sorted.map((d, i) => {
            const ns1Exp = d.sdh_ns1_expected ?? 0;
            const ivfExp = d.sdh_iv_fluid_expected ?? 0;
            const keyRec = d.planning_suggestions[0]?.label ?? "—";
            const genCap = d.general_bed_capacity;

            return (
              <tr key={d.facility_id} className={i % 2 === 0 ? "bg-white" : "bg-slate-50/60"}>

                {/* Facility name */}
                <td className="px-3 py-2.5 max-w-[180px]">
                  <p className="font-semibold text-slate-800 leading-tight truncate">
                    {d.facility_name}
                  </p>
                </td>

                {/* Zone */}
                <td className="px-3 py-2.5 whitespace-nowrap text-slate-600">
                  {d.zone_name}
                </td>

                {/* Anchor type badge */}
                <td className="px-3 py-2.5">
                  <AnchorBadge anchorType={d.facility_anchor_type} />
                </td>

                {/* General bed capacity */}
                <td className="px-3 py-2.5 text-center font-medium text-slate-700">
                  {genCap != null ? (
                    <>
                      {genCap.toLocaleString()}
                      {d.facility_anchor_type === "real_public_hospital_anchor" && (
                        <span className="block text-[10px] text-slate-400 font-normal">ref.</span>
                      )}
                    </>
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>

                {/* Demo dengue beds */}
                <td className="px-3 py-2.5 text-center font-medium text-slate-700">
                  {d.dengue_bed_capacity_demo}
                  <span className="block text-[10px] text-slate-400 font-normal">synthetic</span>
                </td>

                {/* Projected bed load (expected) */}
                <td className="px-3 py-2.5 text-center font-medium text-slate-700">
                  {d.projected_bed_load_expected.toFixed(1)}
                  <span className="text-slate-400 font-normal">/{d.dengue_bed_capacity_demo}</span>
                </td>

                {/* Bed gap expected */}
                <td className="px-3 py-2.5 text-center">
                  <StatusPill
                    label={d.bed_gap_expected > 0 ? `+${d.bed_gap_expected.toFixed(1)}` : "None"}
                    variant={bedGapVariant(d.bed_gap_expected)}
                    size="sm"
                  />
                </td>

                {/* NS1 SDH expected */}
                <td className="px-3 py-2.5 text-center">
                  {ns1Exp > 0 ? (
                    <StatusPill
                      label={`${ns1Exp.toFixed(1)}d`}
                      variant={getSdhSeverity(ns1Exp)}
                      size="sm"
                    />
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>

                {/* IVF SDH expected */}
                <td className="px-3 py-2.5 text-center">
                  {ivfExp > 0 ? (
                    <StatusPill
                      label={`${ivfExp.toFixed(1)}d`}
                      variant={getSdhSeverity(ivfExp)}
                      size="sm"
                    />
                  ) : (
                    <span className="text-slate-400">—</span>
                  )}
                </td>

                {/* Priority category */}
                <td className="px-3 py-2.5 text-center">
                  <StatusPill
                    label={d.priority_category}
                    variant={priorityCategoryVariant(d.priority_category)}
                    size="sm"
                  />
                </td>

                {/* Key recommendation */}
                <td className="px-3 py-2.5 max-w-[240px] text-slate-600 leading-tight">
                  {keyRec}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
