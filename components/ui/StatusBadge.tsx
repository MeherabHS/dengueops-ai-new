import { clsx } from "clsx";
import type { ReactNode } from "react";

type Variant = "success" | "warning" | "destructive" | "info" | "neutral";
const variants: Record<Variant, string> = {
  success: "border-success/25 bg-success/10 text-success",
  warning: "border-warning/25 bg-warning/10 text-warning",
  destructive: "border-destructive/25 bg-destructive/10 text-destructive",
  info: "border-informational/25 bg-informational/10 text-informational",
  neutral: "border-border-subtle bg-surface-muted text-ink-muted",
};

export default function StatusBadge({ label, children, variant = "neutral", className }: { label?: string; children?: ReactNode; variant?: Variant; className?: string }) {
  return <span className={clsx("inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold", variants[variant], className)}>{children ?? label}</span>;
}
