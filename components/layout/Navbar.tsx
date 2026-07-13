"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Menu, X } from "lucide-react";
import { useState } from "react";
import { clsx } from "clsx";
import { NAV_LINKS, PROJECT_TITLE } from "@/lib/constants";
import StatusBadge from "@/components/ui/StatusBadge";

export default function Navbar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-surface/95 shadow-sm backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <Link href="/dashboard" className="group flex items-center gap-2 rounded-md">
          <Activity className="h-6 w-6 text-accent" aria-hidden="true" />
          <span className="text-lg font-bold tracking-tight text-primary">{PROJECT_TITLE}</span>
        </Link>
        <nav aria-label="Primary navigation" className="hidden items-center gap-1 md:flex">
          {NAV_LINKS.map((link) => {
            const active = pathname === link.href;
            return <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined} className={clsx("rounded-md px-3 py-2 text-sm font-medium transition-colors", active ? "bg-accent-soft text-accent" : "text-secondary hover:bg-muted hover:text-primary")}>{link.label}</Link>;
          })}
        </nav>
        <div className="hidden items-center gap-2 xl:flex" aria-label="Deployment status">
          <StatusBadge variant="info">Synthetic Capability Demonstration</StatusBadge>
          <StatusBadge variant="warning">Benchmark Only</StatusBadge>
        </div>
        <button type="button" className="rounded-md p-2 text-secondary hover:bg-muted hover:text-primary md:hidden" onClick={() => setMobileOpen((open) => !open)} aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"} aria-expanded={mobileOpen} aria-controls="mobile-primary-navigation">
          {mobileOpen ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </div>
      {mobileOpen && <div id="mobile-primary-navigation" className="border-t border-border bg-surface px-4 pb-4 md:hidden">
        <nav aria-label="Mobile primary navigation" className="flex flex-col gap-1 pt-3">
          {NAV_LINKS.map((link) => {
            const active = pathname === link.href;
            return <Link key={link.href} href={link.href} aria-current={active ? "page" : undefined} onClick={() => setMobileOpen(false)} className={clsx("rounded-md px-3 py-2 text-sm font-medium", active ? "bg-accent-soft text-accent" : "text-secondary hover:bg-muted")}>{link.label}</Link>;
          })}
        </nav>
        <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
          <StatusBadge variant="info">Synthetic Capability Demonstration</StatusBadge>
          <StatusBadge variant="warning">Benchmark Only</StatusBadge>
        </div>
      </div>}
    </header>
  );
}
