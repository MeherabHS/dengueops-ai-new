import DataTable, { type Column } from "@/components/ui/DataTable";
import StatusPill from "@/components/ui/StatusPill";
import type { Directive } from "@/lib/types";
import { formatNumber } from "@/lib/formatters";
import { Info } from "lucide-react";

interface Props {
  directives: Directive[];
}

/** Build one row per zone, taking the highest priority_score across all facilities. */
function deduplicateByZone(directives: Directive[]): Directive[] {
  const byZone = new Map<string, Directive>();
  for (const d of directives) {
    const existing = byZone.get(d.zone_id);
    // Keep the row with the highest priority_score (worst-case for planning)
    if (!existing || d.priority_score > existing.priority_score) {
      byZone.set(d.zone_id, d);
    }
  }
  return Array.from(byZone.values());
}

/** Map priority category to StatusPill variant. */
function priorityVariant(cat: string): "critical" | "warning" | "info" | "ok" {
  if (cat === "Critical") return "critical";
  if (cat === "High")     return "warning";
  if (cat === "Moderate") return "info";
  return "ok";
}

/** Derive category from score (0–100). Used as safety fallback if category field is stale. */
function deriveCategoryFromScore(score: number): string {
  if (score >= 76) return "Critical";
  if (score >= 51) return "High";
  if (score >= 26) return "Moderate";
  return "Routine";
}

export default function ZoneRiskTable({ directives }: Props) {
  const zoneRows = deduplicateByZone(directives);
  const sorted   = [...zoneRows].sort((a, b) => b.priority_score - a.priority_score);

  const columns: Column<Directive>[] = [
    {
      key: "rank",
      header: "#",
      render: (_, i?: number) => (
        <span className="font-bold text-slate-400">#{(i ?? 0) + 1}</span>
      ),
    },
    { key: "zone_name", header: "Zone" },
    {
      key: "exposure_index",
      header: "Exposure",
      render: (d) => (d.exposure_index * 100).toFixed(0) + "%",
    },
    {
      key: "zone_allocated_cases_expected",
      header: "Alloc. Cases",
      render: (d) => formatNumber(d.zone_allocated_cases_expected),
    },
    {
      key: "priority_score",
      header: "Priority (0–100)",
      render: (d) => (
        <span className="font-bold text-slate-900 tabular-nums">
          {Number(d.priority_score).toFixed(0)}
        </span>
      ),
    },
    {
      key: "priority_category",
      header: "Category",
      render: (d) => {
        // Always re-derive from score to ensure consistency
        const cat = deriveCategoryFromScore(Number(d.priority_score));
        return (
          <StatusPill
            label={cat}
            variant={priorityVariant(cat)}
            size="sm"
          />
        );
      },
    },
  ];

  return (
    <div className="space-y-2">
      <DataTable
        columns={columns}
        data={sorted}
        rowKey={(d) => d.zone_id}
      />
      <p className="flex items-start gap-1.5 text-[10px] text-slate-400 italic px-1">
        <Info className="h-3 w-3 flex-shrink-0 mt-0.5" />
        Priority scores (0–100) incorporate zone exposure index and structural vulnerability
        alongside the current forecast risk. Higher = greater preparedness urgency.
        Scenario simulation is a what-if overlay and does not retrain the forecasting model.
      </p>
    </div>
  );
}
