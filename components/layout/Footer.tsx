import Link from "next/link";
import { Activity } from "lucide-react";
import { PROJECT_TITLE, PROJECT_SUBTITLE, SECONDARY_NAV_LINKS } from "@/lib/constants";

export default function Footer() {
  return (
    <footer className="border-t border-border bg-surface-muted text-secondary">
      <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        <div className="grid gap-6 md:grid-cols-3">
          <div><div className="mb-2 flex items-center gap-2 text-primary"><Activity className="h-5 w-5 text-accent" aria-hidden="true" /><span className="font-bold">{PROJECT_TITLE}</span></div><p className="text-xs leading-relaxed">{PROJECT_SUBTITLE}</p></div>
          <nav aria-label="Secondary navigation"><p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">Learn more</p><ul className="grid grid-cols-2 gap-2 text-sm">{SECONDARY_NAV_LINKS.map((link) => <li key={link.href}><Link href={link.href} className="text-secondary hover:text-accent">{link.label}</Link></li>)}</ul></nav>
          <div><p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted">Disclaimer</p><p className="text-xs leading-relaxed">Synthetic, aggregated demonstration data only. Outputs are advisory and require qualified public-health review before any real-world use.</p></div>
        </div>
        <div className="mt-8 border-t border-border pt-4 text-center text-xs text-muted">© {new Date().getFullYear()} DengueOps AI. Research and educational demonstration only.</div>
      </div>
    </footer>
  );
}
