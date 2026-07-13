import type { Metadata } from "next";
import AssumptionsHero from "@/components/assumptions/AssumptionsHero";
import CoreAssumptionsTable from "@/components/assumptions/CoreAssumptionsTable";
import DataBoundaryTable from "@/components/assumptions/DataBoundaryTable";
import OperationalWorkflowAssumption from "@/components/assumptions/OperationalWorkflowAssumption";
import LimitationsSection from "@/components/assumptions/LimitationsSection";
import FutureValidationRoadmap from "@/components/assumptions/FutureValidationRoadmap";

export const metadata: Metadata = {
  title: "Assumptions & Limitations — DengueOps AI",
  description:
    "Transparent documentation of all assumptions, data boundaries, spatial heuristics, modelling limitations, decision-support scope, and future validation requirements for DengueOps AI.",
};

const JUMP_LINKS = [
  { href: "#core-assumptions",    label: "Core Assumptions"    },
  { href: "#data-boundary",       label: "Real vs Synthetic"   },
  { href: "#operational-workflow",label: "Operational Workflow" },
  { href: "#modeling-limits",     label: "Modelling Limits"    },
  { href: "#decision-limits",     label: "Decision-Support"    },
  { href: "#misuse-risks",        label: "Misuse Risks"        },
  { href: "#roadmap",             label: "Roadmap"             },
  { href: "#final-summary",       label: "Summary"             },
];

export default function AssumptionsPage() {
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
              href="/ethics"
              className="ml-auto whitespace-nowrap rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600 hover:bg-slate-100 transition-colors flex-shrink-0"
            >
              Ethics →
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
        <AssumptionsHero />

        <hr className="border-slate-200 mb-12" />

        {/* 2. Core Assumptions Table */}
        <CoreAssumptionsTable />

        <hr className="border-slate-200 mb-12" />

        {/* 3. Data Boundary + Spatial Assumption */}
        <DataBoundaryTable />

        <hr className="border-slate-200 mb-12" />

        {/* 4. Operational Workflow Assumption */}
        <OperationalWorkflowAssumption />

        <hr className="border-slate-200 mb-12" />

        {/* 5. Modelling + Decision-Support + Misuse Risks */}
        <LimitationsSection />

        <hr className="border-slate-200 mb-12 mt-14" />

        {/* 6. Roadmap + Final Summary */}
        <FutureValidationRoadmap />

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
