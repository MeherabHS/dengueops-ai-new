import type { Metadata } from "next";
import EthicsHero from "@/components/ethics/EthicsHero";
import EthicalPrinciples from "@/components/ethics/EthicalPrinciples";
import DataEthicsSection from "@/components/ethics/DataEthicsSection";
import SafetyBoundaries from "@/components/ethics/SafetyBoundaries";
import UserResponsibilities from "@/components/ethics/UserResponsibilities";

export const metadata: Metadata = {
  title: "Ethics & Responsible Use — DengueOps AI",
  description:
    "Privacy-safe, human-in-the-loop decision support for dengue preparedness. Ethical design principles, data boundaries, safety constraints, and responsible use guidelines.",
};

const JUMP_LINKS = [
  { href: "#principles",      label: "Principles"        },
  { href: "#data-ethics",     label: "Data Ethics"       },
  { href: "#safety-boundaries",label: "Safety Boundaries"},
  { href: "#output-design",   label: "Output Design"     },
  { href: "#user-roles",      label: "User Roles"        },
  { href: "#future-ethics",   label: "Future Deployment" },
  { href: "#ethics-summary",  label: "Summary"           },
];

export default function EthicsPage() {
  return (
    <div className="min-h-screen bg-slate-50">
      {/* Navigation bar */}
      <nav className="sticky top-0 z-30 bg-white/95 backdrop-blur border-b border-slate-200 shadow-sm">
        <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-1 overflow-x-auto py-2.5 scrollbar-hide">
            <a
              href="/"
              className="whitespace-nowrap text-[11px] font-semibold text-slate-400 hover:text-slate-700 mr-3 flex-shrink-0"
            >
              ← Home
            </a>
            {JUMP_LINKS.map((l) => (
              <a
                key={l.href}
                href={l.href}
                className="whitespace-nowrap rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600 hover:bg-sky-50 hover:text-sky-700 hover:border-sky-200 transition-colors flex-shrink-0"
              >
                {l.label}
              </a>
            ))}
            <a
              href="/assumptions"
              className="ml-auto whitespace-nowrap rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-100 transition-colors flex-shrink-0"
            >
              Assumptions →
            </a>
            <a
              href="/dashboard"
              className="whitespace-nowrap rounded-full bg-[#0f172a] px-4 py-1 text-[11px] font-semibold text-white hover:bg-slate-700 transition-colors flex-shrink-0"
            >
              Dashboard →
            </a>
          </div>
        </div>
      </nav>

      <main className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8 py-10 lg:py-14">

        {/* 1. Hero */}
        <EthicsHero />

        <hr className="border-slate-200 mb-12" />

        {/* 2. Ethical Design Principles */}
        <EthicalPrinciples />

        <hr className="border-slate-200 mb-12" />

        {/* 3. Data Ethics */}
        <DataEthicsSection />

        <hr className="border-slate-200 mb-12" />

        {/* 4. Safety Boundaries + 5. Responsible Output Design */}
        <SafetyBoundaries />

        <hr className="border-slate-200 mb-12 mt-14" />

        {/* 6. User Roles + 7. Future Deployment + 8. Ethics Summary */}
        <UserResponsibilities />

        {/* Footer spacer */}
        <div className="mt-20 pb-10 flex items-center justify-center">
          <p className="text-[11px] text-slate-400 text-center max-w-lg leading-relaxed">
            DengueOps AI — Simulation-Based Dengue Surge Preparedness Decision Support for Dhaka South.
            &nbsp;Prototype only. Not for clinical or official public health use.
          </p>
        </div>
      </main>
    </div>
  );
}
