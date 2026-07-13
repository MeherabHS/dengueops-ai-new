"use client";

import { clsx } from "clsx";
import type { ScenarioKey } from "@/lib/types";

interface Props {
  active: ScenarioKey;
  onChange: (s: ScenarioKey) => void;
}

const SCENARIOS: ScenarioKey[] = ["best_case", "expected_case", "worst_case"];
const LABELS: Record<ScenarioKey,string> = { best_case: "Planning Low", expected_case: "Planning Base", worst_case: "Planning High" };

export default function ScenarioSelector({ active, onChange }: Props) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="mr-1 text-xs font-semibold uppercase tracking-wider text-secondary">
        Planning scenario:
      </span>
      {SCENARIOS.map((key) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={clsx(
            "rounded-full px-3 py-1 text-xs font-semibold border transition-all",
            active === key
              ? "border-accent bg-accent text-page"
              : "border-border bg-surface-raised text-secondary hover:border-accent"
          )}
        >
          {LABELS[key]}
        </button>
      ))}
    </div>
  );
}
