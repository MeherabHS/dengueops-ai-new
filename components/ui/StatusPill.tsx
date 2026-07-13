import { clsx } from "clsx";

type StatusVariant = "ok" | "warning" | "critical" | "neutral" | "info";

interface StatusPillProps {
  label: string;
  variant?: StatusVariant;
  size?: "sm" | "md";
  className?: string;
}

const variantClass: Record<StatusVariant, string> = {
  ok: "bg-emerald-100 text-emerald-800 border border-emerald-300",
  warning: "bg-amber-100 text-amber-800 border border-amber-300",
  critical: "bg-red-100 text-red-800 border border-red-300",
  neutral: "bg-slate-100 text-slate-600 border border-slate-200",
  info: "bg-sky-100 text-sky-800 border border-sky-300",
};

export default function StatusPill({
  label,
  variant = "neutral",
  size = "md",
  className,
}: StatusPillProps) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full font-semibold",
        variantClass[variant],
        size === "sm" && "px-2 py-0.5 text-xs",
        size === "md" && "px-2.5 py-1 text-sm",
        className
      )}
    >
      {label}
    </span>
  );
}
