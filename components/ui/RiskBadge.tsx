import { clsx } from "clsx";
import type { RiskLevel } from "@/lib/types";
import { getRiskColor } from "@/lib/risk-utils";

interface RiskBadgeProps {
  level: RiskLevel;
  size?: "sm" | "md" | "lg";
  className?: string;
}

export default function RiskBadge({ level, size = "md", className }: RiskBadgeProps) {
  const colors = getRiskColor(level);

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
