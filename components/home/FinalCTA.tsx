import Link from "next/link";
import { ArrowRight, BarChart3, BookOpen, FlaskConical, ShieldCheck } from "lucide-react";

const LINKS = [
  { href: "/dashboard",    label: "Launch Dashboard",  icon: <BarChart3 className="h-4 w-4" />,    primary: true  },
  { href: "/methodology",  label: "Methodology",        icon: <BookOpen className="h-4 w-4" />,     primary: false },
  { href: "/validation",   label: "Validation",          icon: <FlaskConical className="h-4 w-4" />, primary: false },
  { href: "/ethics",       label: "Ethics",              icon: <ShieldCheck className="h-4 w-4" />,  primary: false },
];

export default function FinalCTA() {
  return (
    <section className="bg-[#0f172a]">
      <div className="mx-auto max-w-5xl px-4 py-20 sm:px-6 lg:px-8 text-center">
        <p className="text-xs font-semibold uppercase tracking-widest text-sky-400 mb-3">
          IEEE ICADHI Project Showcase
        </p>
        <h2 className="text-3xl font-extrabold text-white mb-4 leading-tight">
          Explore the Preparedness Dashboard
        </h2>
        <p className="text-slate-400 mb-10 max-w-2xl mx-auto text-sm leading-relaxed">
          View the complete prototype dashboard with forecast uncertainty, model validation,
          zone priorities, facility readiness, supply depletion timelines, and
          operational directives — all generated from the analytics pipeline.
        </p>

        <div className="flex flex-wrap justify-center gap-3">
          {LINKS.map((l) =>
            l.primary ? (
              <Link
                key={l.href}
                href={l.href}
                className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-6 py-3 text-sm font-semibold text-white shadow-lg hover:bg-sky-400 transition-colors"
              >
                {l.icon}
                {l.label}
                <ArrowRight className="h-4 w-4" />
              </Link>
            ) : (
              <Link
                key={l.href}
                href={l.href}
                className="inline-flex items-center gap-2 rounded-lg border border-slate-600 bg-white/5 px-5 py-3 text-sm font-semibold text-slate-300 hover:bg-white/10 hover:text-white transition-colors"
              >
                {l.icon}
                {l.label}
              </Link>
            )
          )}
        </div>

        <p className="mt-10 text-[11px] text-slate-600 max-w-xl mx-auto leading-relaxed">
          Synthetic demonstration data · Advisory outputs only · No patient-level data ·
          Human review required before any operational action.
        </p>
      </div>
    </section>
  );
}
