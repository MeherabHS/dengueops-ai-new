import type { Metadata } from "next";
import MethodologyHero from "@/components/methodology/MethodologyHero";
import PipelineOverview from "@/components/methodology/PipelineOverview";
import DataInputLayer from "@/components/methodology/DataInputLayer";
import FeatureEngineeringSection from "@/components/methodology/FeatureEngineeringSection";
import ValidationMethodSection from "@/components/methodology/ValidationMethodSection";
import OperationalLogicSection from "@/components/methodology/OperationalLogicSection";
import LimitationsSection from "@/components/methodology/LimitationsSection";

export const metadata: Metadata = {
  title: "Methodology — DengueOps AI",
  description:
    "Full analytical methodology for DengueOps AI: lag-aware feature engineering, temporal backtesting, prior-only empirical forecast ranges, spatial exposure allocation, SDH supply depletion, LOS bed pressure, vulnerability-gated priority scoring, and human-in-the-loop directives.",
};

const JUMP_LINKS = [
  { href: "#pipeline",    label: "Pipeline" },
  { href: "#data",        label: "Data Inputs" },
  { href: "#features",    label: "Feature Engineering" },
  { href: "#validation",  label: "Validation" },
  { href: "#forecasting", label: "Forecasting" },
  { href: "#uncertainty", label: "Uncertainty" },
  { href: "#spatial",     label: "Spatial Allocation" },
  { href: "#sdh",         label: "SDH" },
  { href: "#bed-pressure",label: "Bed Pressure" },
  { href: "#priority",    label: "Priority Score" },
  { href: "#directives",  label: "Directives" },
  { href: "#human-in-loop", label: "Human-in-loop" },
  { href: "#limitations", label: "Limitations" },
  { href: "#future",      label: "Future" },
];

export default function MethodologyPage() {
  return (
    <div className="bg-[#f8fafc] min-h-screen">
      <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 lg:px-8">

        {/* ── Hero ────────────────────────────────────────────────────── */}
        <MethodologyHero />

        {/* ── Jump navigation ─────────────────────────────────────────── */}
        <nav className="mb-12 overflow-x-auto">
          <div className="flex flex-wrap gap-2 border border-slate-200 bg-white rounded-xl px-4 py-3 shadow-sm">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 self-center mr-1">
              Jump to:
            </span>
            {JUMP_LINKS.map((link) => (
              <a
                key={link.href}
                href={link.href}
                className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-[11px] font-medium text-slate-600 hover:border-sky-300 hover:bg-sky-50 hover:text-sky-700 transition-colors"
              >
                {link.label}
              </a>
            ))}
          </div>
        </nav>

        {/* ── Divider helper ─────────────────────────────────────────── */}
        {/* 1+2. Pipeline Overview */}
        <PipelineOverview />

        <hr className="border-slate-200 mb-14" />

        {/* 3. Data Input Layer */}
        <DataInputLayer />

        <hr className="border-slate-200 mb-14" />

        {/* 4. Feature Engineering */}
        <FeatureEngineeringSection />

        <hr className="border-slate-200 mb-14" />

        {/* 5. Temporal Backtesting */}
        <ValidationMethodSection />

        <hr className="border-slate-200 mb-14" />

        {/* 6–12. Operational Logic (forecasting → directives) */}
        <OperationalLogicSection />

        <hr className="border-slate-200 mb-14 mt-14" />

        {/* 13–15. Human-in-loop · Limitations · Future */}
        <LimitationsSection />

        {/* ── Footer disclaimer ─────────────────────────────────────── */}
        <div className="mt-16 rounded-xl border border-slate-200 bg-white px-5 py-5 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
            Document scope
          </p>
          <p className="text-xs text-slate-500 leading-relaxed max-w-2xl">
            This methodology documentation is produced for the IEEE ICADHI 2026 Project Showcase,
            Track 06: Health Data Analytics &amp; Predictive Systems. All values referenced are from
            synthetic demonstration data. This prototype is not a deployment-ready system.
            Human review is required before any operational action based on these outputs.
          </p>
        </div>
      </div>
    </div>
  );
}
