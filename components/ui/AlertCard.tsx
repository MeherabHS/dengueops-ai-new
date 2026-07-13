import { clsx } from "clsx";
import { AlertTriangle, AlertCircle, CheckCircle, Info } from "lucide-react";
import type { ReactNode } from "react";

type AlertVariant = "critical" | "warning" | "success" | "info";

interface AlertCardProps {
  variant: AlertVariant;
  title: string;
  children: ReactNode;
  className?: string;
}

const config: Record<
  AlertVariant,
  { bg: string; border: string; text: string; icon: ReactNode }
> = {
  critical: {
    bg: "bg-red-50",
    border: "border-red-300",
    text: "text-red-800",
    icon: <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />,
  },
  warning: {
    bg: "bg-amber-50",
    border: "border-amber-300",
    text: "text-amber-800",
    icon: <AlertTriangle className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />,
  },
  success: {
    bg: "bg-emerald-50",
    border: "border-emerald-300",
    text: "text-emerald-800",
    icon: <CheckCircle className="h-5 w-5 text-emerald-600 flex-shrink-0 mt-0.5" />,
  },
  info: {
    bg: "bg-sky-50",
    border: "border-sky-300",
    text: "text-sky-800",
    icon: <Info className="h-5 w-5 text-sky-600 flex-shrink-0 mt-0.5" />,
  },
};

export default function AlertCard({ variant, title, children, className }: AlertCardProps) {
  const c = config[variant];
  return (
    <div
      className={clsx(
        "rounded-xl border p-4 flex gap-3",
        c.bg,
        c.border,
        className
      )}
    >
      {c.icon}
      <div>
        <p className={clsx("text-sm font-semibold", c.text)}>{title}</p>
        <div className={clsx("text-sm mt-1", c.text)}>{children}</div>
      </div>
    </div>
  );
}
