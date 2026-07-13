import { clsx } from "clsx";
import type { ReactNode } from "react";

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  badge?: ReactNode;
  className?: string;
}

export default function SectionHeader({
  title,
  subtitle,
  badge,
  className,
}: SectionHeaderProps) {
  return (
    <div className={clsx("mb-6", className)}>
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-bold text-slate-900">{title}</h2>
        {badge}
      </div>
      {subtitle && (
        <p className="mt-1 text-sm text-slate-500 max-w-2xl">{subtitle}</p>
      )}
      <div className="mt-3 h-px bg-slate-200" />
    </div>
  );
}
