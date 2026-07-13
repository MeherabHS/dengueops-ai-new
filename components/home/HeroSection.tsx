import Link from "next/link";
import { ArrowRight, Activity, ShieldCheck, BarChart3, Zap } from "lucide-react";
import { PROJECT_TITLE, PROJECT_SUBTITLE, ICADHI_TRACK, CONFERENCE } from "@/lib/constants";

const BADGES = [
  { label: ICADHI_TRACK, icon: <BarChart3 className="h-3 w-3" /> },
  { label: "Health Data Analytics & Predictive Systems", icon: <Activity className="h-3 w-3" /> },
  { label: "No patient-level data", icon: <ShieldCheck className="h-3 w-3" /> },
  { label: "Forecast-to-Preparedness DSS", icon: <Zap className="h-3 w-3" /> },
];

export default function HeroSection() {
  return (
    <section className="relative overflow-hidden bg-[#0f172a] text-white">
      {/* Gradient backdrop */}
      <div className="absolute inset-0 bg-gradient-to-br from-[#0f172a] via-[#1e3a5f] to-[#0f172a] opacity-95 pointer-events-none" />
      {/* Subtle grid pattern */}
      <div
        className="absolute inset-0 opacity-[0.04] pointer-events-none"
        style={{
          backgroundImage:
            "linear-gradient(#ffffff 1px, transparent 1px), linear-gradient(90deg, #ffffff 1px, transparent 1px)",
          backgroundSize: "40px 40px",
        }}
      />

      <div className="relative mx-auto max-w-5xl px-4 py-20 sm:px-6 sm:py-28 lg:px-8">
        {/* Conference badge */}
        <div className="mb-5">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-sky-400/30 bg-sky-400/10 px-3 py-1 text-xs font-semibold uppercase tracking-widest text-sky-400">
            <Activity className="h-3 w-3" />
            {CONFERENCE} &middot; Project Showcase
          </span>
        </div>

        {/* Title */}
        <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl lg:text-6xl leading-tight mb-3">
          {PROJECT_TITLE}
        </h1>

        {/* Subtitle */}
        <p className="max-w-2xl text-xl font-medium text-sky-200 leading-snug mb-5">
          {PROJECT_SUBTITLE}
        </p>

        {/* Short pitch */}
        <p className="max-w-2xl text-base text-slate-300 leading-relaxed mb-8 italic">
          &ldquo;Converting lag-aware dengue forecasts into supply depletion timelines,
          bed pressure estimates, uncertainty scenarios, and public health action priorities.&rdquo;
        </p>

        {/* CTA buttons */}
        <div className="flex flex-wrap gap-3 mb-10">
          <Link
            href="/dashboard"
            className="inline-flex items-center gap-2 rounded-lg bg-sky-500 px-5 py-2.5 text-sm font-semibold text-white shadow-lg hover:bg-sky-400 transition-colors"
          >
            View Dashboard <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/methodology"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-500 bg-white/5 px-5 py-2.5 text-sm font-semibold text-slate-200 hover:bg-white/10 transition-colors"
          >
            See Methodology
          </Link>
          <Link
            href="/validation"
            className="inline-flex items-center gap-2 rounded-lg border border-slate-500 bg-white/5 px-5 py-2.5 text-sm font-semibold text-slate-200 hover:bg-white/10 transition-colors"
          >
            View Validation
          </Link>
        </div>

        {/* Feature badges */}
        <div className="flex flex-wrap gap-2 mb-10">
          {BADGES.map((b) => (
            <span
              key={b.label}
              className="inline-flex items-center gap-1.5 rounded-full border border-sky-800 bg-sky-950/50 px-3 py-1 text-[11px] font-medium text-sky-300"
            >
              {b.icon}
              {b.label}
            </span>
          ))}
        </div>

        {/* Technical positioning note */}
        <div className="max-w-2xl rounded-xl border border-sky-900 bg-[#0f172a]/60 px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-sky-500 mb-1.5">
            Technical Positioning
          </p>
          <p className="text-sm text-sky-300 leading-relaxed">
            This prototype does not claim a novel forecasting algorithm.
            Its contribution is the{" "}
            <span className="font-semibold text-sky-200">operational decision-support layer</span>
            {" "}that translates outbreak forecasts into preparedness intelligence:{" "}
            supply depletion timelines, LOS-based bed pressure estimates,
            spatial zone priorities, and actionable directives.
          </p>
        </div>
      </div>
    </section>
  );
}
