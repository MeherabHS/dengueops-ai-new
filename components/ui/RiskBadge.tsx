import { clsx } from "clsx";
import type { ForecastGrowthCategory } from "@/lib/types";

interface RiskBadgeProps {
  level: ForecastGrowthCategory;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export default function RiskBadge({ level, size = "md", className }: RiskBadgeProps) {
  const colors = {
    "Low forecast growth": { bg: "bg-emerald-100", text: "text-emerald-800", border: "border-emerald-300" },
    "Moderate forecast growth": { bg: "bg-yellow-100", text: "text-yellow-800", border: "border-yellow-300" },
    "High forecast growth": { bg: "bg-orange-100", text: "text-orange-800", border: "border-orange-300" },
    "Very high forecast growth": { bg: "bg-red-100", text: "text-red-800", border: "border-red-300" },
  }[level];

  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full font-semibold",
        colors.bg,
        colors.text,
        `border ${colors.border}`,
        size === "sm" && "px-2 py-0.5 text-xs",
        size === "md" && "px-2.5 py-1 text-sm",
        size === "lg" && "px-3 py-1.5 text-base",
        className
      )}
    >
      {level}
    </span>
  );
}
