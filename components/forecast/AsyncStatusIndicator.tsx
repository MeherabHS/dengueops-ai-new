"use client";

import { useEffect, useState } from "react";
import { LoaderCircle } from "lucide-react";
import Button from "@/components/ui/Button";

function elapsedLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s elapsed`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, "0")}s elapsed`;
}

export default function AsyncStatusIndicator({
  label,
  detail,
  delayedAfterSeconds = 10,
  delayedMessage = "This is taking longer than usual. The existing operation is still being checked safely.",
  onCheckStatus,
  checkDisabled = false,
}: {
  label: string;
  detail?: string | null;
  delayedAfterSeconds?: number;
  delayedMessage?: string;
  onCheckStatus?: () => void;
  checkDisabled?: boolean;
}) {
  const [startedAt] = useState(() => Date.now());
  const [clock, setClock] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClock(Date.now());
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const elapsedSeconds = Math.max(0, Math.floor((clock - startedAt) / 1000));
  return (
    <div className="rounded-lg border border-accent/25 bg-accent/5 p-3" role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-sm font-semibold text-ink">
        <LoaderCircle className="h-4 w-4 animate-spin text-accent" aria-hidden="true" />
        <span>{label}</span>
      </div>
      {detail ? <p className="mt-1 text-xs text-ink-muted">{detail}</p> : null}
      <p className="mt-1 text-xs tabular-nums text-text-muted">{elapsedLabel(elapsedSeconds)}</p>
      {elapsedSeconds >= delayedAfterSeconds ? <p className="mt-2 text-xs text-warning">{delayedMessage}</p> : null}
      {onCheckStatus ? <Button className="mt-3" variant="secondary" disabled={checkDisabled} onClick={onCheckStatus}>Check status</Button> : null}
    </div>
  );
}
