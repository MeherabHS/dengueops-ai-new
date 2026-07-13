"use client";

import { useId, useState } from "react";
import type { ReactNode, KeyboardEvent } from "react";
import { clsx } from "clsx";

export interface TabItem { id: string; label: string; content: ReactNode; }

export default function Tabs({ items, initialTab }: { items: TabItem[]; initialTab?: string }) {
  const [active, setActive] = useState(initialTab ?? items[0]?.id ?? "");
  const baseId = useId();
  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!items.length) return;
    const next = event.key === "ArrowRight" ? (index + 1) % items.length : event.key === "ArrowLeft" ? (index - 1 + items.length) % items.length : null;
    if (next !== null) { event.preventDefault(); setActive(items[next].id); document.getElementById(`${baseId}-tab-${items[next].id}`)?.focus(); }
  };
  return <div>
    <div className="flex gap-1 overflow-x-auto border-b border-border-subtle" role="tablist" aria-label="Evidence sections">
      {items.map((item, index) => <button key={item.id} id={`${baseId}-tab-${item.id}`} role="tab" aria-selected={active === item.id} aria-controls={`${baseId}-panel-${item.id}`} tabIndex={active === item.id ? 0 : -1} onKeyDown={(e) => move(e,index)} onClick={() => setActive(item.id)} className={clsx("whitespace-nowrap border-b-2 px-4 py-3 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus", active === item.id ? "border-accent text-accent" : "border-transparent text-ink-muted hover:text-ink")}>{item.label}</button>)}
    </div>
    {items.map(item => <section key={item.id} id={`${baseId}-panel-${item.id}`} role="tabpanel" aria-labelledby={`${baseId}-tab-${item.id}`} hidden={active !== item.id} className="pt-6">{item.content}</section>)}
  </div>;
}
