import type { ReactNode } from "react";

export default function EmptyState({ title, description, action }: { title: string; description: string; action?: ReactNode }) {
  return <div className="rounded-xl border border-dashed border-border-subtle bg-surface-muted p-6 text-center" role="status">
    <p className="font-semibold text-ink">{title}</p><p className="mx-auto mt-1 max-w-lg text-sm text-ink-muted">{description}</p>{action && <div className="mt-4">{action}</div>}
  </div>;
}
