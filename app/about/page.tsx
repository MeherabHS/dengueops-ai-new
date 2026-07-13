import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import SectionHeader from "@/components/ui/SectionHeader";
import AlertCard from "@/components/ui/AlertCard";
import OperationalWorkflowCard from "@/components/dashboard/OperationalWorkflowCard";
import AuthorsSection from "@/components/ui/AuthorsSection";
import { PROJECT_TITLE, PROJECT_SUBTITLE, ICADHI_TRACK, CONFERENCE } from "@/lib/constants";

export const metadata: Metadata = { title: "About" };

export default function AboutPage() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-12 sm:px-6 lg:px-8">
      <div className="mb-10">
        <span className="text-xs font-semibold uppercase tracking-wider text-sky-600">
          Project Overview
        </span>
        <h1 className="mt-2 text-3xl font-extrabold text-slate-900">{PROJECT_TITLE}</h1>
        <p className="mt-2 text-slate-500">{PROJECT_SUBTITLE}</p>
        <p className="mt-1 text-xs text-slate-400">
          {CONFERENCE} &middot; {ICADHI_TRACK}
        </p>
      </div>

      {/* ── What it is ── */}
      <SectionHeader title="What DengueOps AI Is" />
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm mb-8">
        <p className="text-sm text-slate-700 leading-relaxed mb-4">
          DengueOps AI is a <strong>simulation-based public health decision-support prototype</strong>{" "}
          that converts lag-aware dengue outbreak forecasts into operational preparedness
          intelligence for Dhaka South, Bangladesh.
        </p>
        <p className="text-sm text-slate-700 leading-relaxed mb-4">
          It takes a city-level dengue case forecast and produces:
        </p>
        <ul className="space-y-2 text-sm text-slate-600">
          {[
            "Separate empirical forecast-range evidence and preparedness planning scenarios",
            "Supply Depletion Horizon (SDH) for NS1/RDT kits and IV fluids per facility",
            "Projected bed load and bed gap estimates using LOS approximation",
            "Zone priority scores via a spatial exposure heuristic",
            "Tiered operational directives per zone and facility",
          ].map((item) => (
            <li key={item} className="flex gap-2">
              <span className="text-sky-600 font-bold shrink-0">→</span>
              {item}
            </li>
          ))}
        </ul>
      </div>

      {/* ── Intended audience ── */}
      <SectionHeader title="Intended Audience & Role Design" />
      <div className="rounded-xl border border-[#1e3a5f] bg-[#0f172a] px-5 py-4 shadow-sm mb-4">
        <p className="text-sm font-semibold text-white mb-2">
          RMSE and model metrics are not intended for public users.
        </p>
        <p className="text-xs text-sky-300 leading-relaxed">
          They are included for technical validation and evaluator transparency.
          Operational users receive translated action recommendations — zone priorities,
          supply depletion timelines, bed pressure signals, and plain-language directives.
          The dashboard uses role-based tabs to serve each audience with only the information
          relevant to their decision-making context.
        </p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 mb-8">
        {[
          { role: "Operational Command", audience: "Public health officials, DSCC vector-control teams, emergency planners", sees: "Zone priorities, risk levels, directives, scenario projections" },
          { role: "Facility Readiness", audience: "Hospital administrators, diagnostic centre managers", sees: "NS1/RDT SDH, IV fluid SDH, bed load, bed gap, supply alerts" },
          { role: "Public Advisory", audience: "Future citizen-facing layer (preview)", sees: "Simplified risk status, prevention guidance, when to seek care" },
          { role: "Technical Validation", audience: "IEEE judges, researchers, MSc evaluators", sees: "MAE, RMSE, MAPE, backtest results, feature importance, uncertainty methodology" },
        ].map((item) => (
          <div key={item.role} className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
            <p className="text-sm font-semibold text-slate-800">{item.role}</p>
            <p className="text-xs text-slate-500 mt-0.5 mb-2">{item.audience}</p>
            <p className="text-xs text-sky-700 bg-sky-50 rounded px-2 py-1">{item.sees}</p>
          </div>
        ))}
      </div>

      {/* ── Operational Workflow ── */}
      <SectionHeader
        title="Operational Workflow"
        subtitle="How the system separates data engineering from operational decision-making."
      />
      <div className="mb-8">
        <OperationalWorkflowCard compact={false} />
      </div>

      {/* ── What it is NOT ── */}
      <SectionHeader title="What DengueOps AI Is Not" />
      <AlertCard variant="info" title="Framing notice for judges" className="mb-8">
        <ul className="space-y-1.5 mt-2 text-xs">
          {[
            "NOT a universally suitable forecasting algorithm — Random Forest is the current synthetic demonstration model",
            "NOT a clinical decision-support tool — no patient-level data, no diagnosis, no triage",
            "NOT a real-time surveillance system in Phase 0 — static placeholder data only",
            "NOT a validated operational system — Phase 0 requires further validation before deployment",
            "NOT an autonomous system — all outputs are advisory and require human review",
          ].map((item) => (
            <li key={item} className="flex gap-2">
              <span className="font-bold shrink-0">✕</span>
              {item}
            </li>
          ))}
        </ul>
      </AlertCard>

      {/* ── Why useful ── */}
      <SectionHeader title="Why It Is Useful" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 mb-8">
        {[
          {
            title: "Fills the preparedness gap",
            desc: "Converts forecast outputs — which are typically unused for supply or bed planning — into actionable operational metrics.",
          },
          {
            title: "Designed for data-scarce settings",
            desc: "The spatial exposure heuristic and SDH calculation work without ward-level case counts or real-time facility feeds.",
          },
          {
            title: "Transparent and auditable",
            desc: "All assumptions are disclosed. The system is explainable by design — formula-based, not black-box output.",
          },
          {
            title: "Human-in-the-loop by architecture",
            desc: "Directives are advisory. The system enhances, not replaces, professional public health judgement.",
          },
          {
            title: "Portfolio and showcase strength",
            desc: "The end-to-end pipeline — from feature engineering to operational directives — demonstrates applied health data science methodology.",
          },
          {
            title: "Scalable architecture",
            desc: "The modular Python analytics pipeline is designed to scale: adding new cities, data sources, or model types requires only module replacement.",
          },
        ].map((item) => (
          <div
            key={item.title}
            className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          >
            <p className="text-sm font-semibold text-slate-900">{item.title}</p>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">{item.desc}</p>
          </div>
        ))}
      </div>

      {/* ── Scalability ── */}
      <SectionHeader title="Future Scalability" />
      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm mb-8">
        <div className="space-y-3 text-sm text-slate-600">
          {[
            { phase: "Phase 1", desc: "Integrate DGHS/IEDCR aggregate surveillance feeds; validate on local ground truth; FastAPI backend" },
            { phase: "Phase 2", desc: "Multi-city deployment; validated spatial model; real-time inventory API integration" },
            { phase: "Phase 3", desc: "Automated directive generation pipeline; health authority integration; Bangla language interface" },
            { phase: "Research", desc: "Calibrated probabilistic forecasting; causal climate-dengue modelling; SDH sensitivity analysis" },
          ].map((item) => (
            <div key={item.phase} className="flex gap-3">
              <span className="font-mono text-xs font-bold text-sky-700 bg-sky-50 border border-sky-200 rounded px-1.5 py-0.5 shrink-0 h-fit">
                {item.phase}
              </span>
              <p className="text-sm text-slate-600">{item.desc}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Core Statement ── */}
      <div className="rounded-xl bg-[#0f172a] p-6 text-white mb-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-400 mb-3">
          Core Contribution Statement
        </p>
        <blockquote className="text-sm leading-relaxed text-slate-300 italic border-l-4 border-sky-500 pl-4">
          &ldquo;DengueOps AI does not claim a novel forecasting algorithm. Its contribution is the
          operational decision-support layer that converts lag-aware outbreak forecasts into
          uncertainty-aware preparedness metrics and public health action priorities.&rdquo;
        </blockquote>
      </div>

      <div className="flex gap-3 flex-wrap">
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-5 py-2.5 text-sm font-semibold text-white hover:bg-sky-400 transition-colors"
        >
          Open Dashboard <ArrowRight className="h-4 w-4" />
        </Link>
        <Link
          href="/methodology"
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition-colors"
        >
          View Methodology
        </Link>
      </div>

      {/* ── Authors ── */}
      <AuthorsSection />
    </div>
  );
}
