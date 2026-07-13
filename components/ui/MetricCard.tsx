import { clsx } from "clsx";
import type { ReactNode } from "react";

interface MetricCardProps {
  title: string;
  value: ReactNode;
  subtitle?: string;
  icon?: ReactNode;
  variant?: "default" | "critical" | "warning" | "success" | "info";
  className?: string;
}

const variantStyles = {
  default: "border-border bg-surface-raised",
  critical: "border-destructive/30 bg-destructive/10",
  warning: "border-warning/30 bg-warning/10",
  success: "border-success/30 bg-success/10",
  info: "border-informational/30 bg-informational/10",
};

const titleStyles = {
  default: "text-secondary",
  critical: "text-destructive",
  warning: "text-warning",
  success: "text-success",
  info: "text-informational",
};

export default function MetricCard({
  title,
  value,
  subtitle,
  icon,
  variant = "default",
  className,
}: MetricCardProps) {
  return (
    <div
      className={clsx(
        "rounded-xl border p-4 shadow-sm flex flex-col gap-2",
        variantStyles[variant],
        className
      )}
    >
      <div className="flex items-center justify-between">
        <p className={clsx("text-xs font-semibold uppercase tracking-wider", titleStyles[variant])}>
          {title}
        </p>
        {icon && <span className="text-secondary">{icon}</span>}
      </div>
      <p className="text-2xl font-bold text-primary leading-tight">{value}</p>
      {subtitle && <p className="text-xs text-secondary">{subtitle}</p>}
    </div>
  );
}
