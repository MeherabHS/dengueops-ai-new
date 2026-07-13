import { Users, Info, ShieldCheck, Stethoscope, Bug, Droplets, CheckCircle2 } from "lucide-react";
import RiskBadge from "@/components/ui/RiskBadge";
import type { ForecastOutput } from "@/lib/types";
import type { RiskLevel } from "@/lib/types";

interface Props {
  forecast: ForecastOutput;
}

// ── Static prevention guidance (not case-count dependent) ─────────────────

const PREVENTION_STEPS = [
  { icon: <Droplets className="h-4 w-4 text-sky-500" />, text: "Remove standing water from flower pots, tyres, and containers around your home weekly." },
  { icon: <Bug className="h-4 w-4 text-sky-500" />, text: "Use mosquito nets, window screens, or air conditioning during Aedes biting hours (early morning and late afternoon)." },
  { icon: <ShieldCheck className="h-4 w-4 text-sky-500" />, text: "Apply mosquito repellent (DEET, picaridin, or IR3535-based) when outdoors in the ward." },
  { icon: <Droplets className="h-4 w-4 text-sky-500" />, text: "Report blocked drains or water accumulation to the city corporation sanitation hotline." },
];

const SEEK_CARE_STEPS = [
  "Sudden high fever (38.5°C or above) lasting more than 2 days.",
  "Severe headache, pain behind the eyes, or joint and muscle pain.",
  "Skin rash appearing after the fever starts.",
  "Bleeding from the nose or gums, or blood in urine or stool.",
  "Vomiting, persistent abdominal pain, or restlessness — these may indicate severe dengue.",
];

// ── Translated risk messages ──────────────────────────────────────────────

const RISK_MESSAGES: Record<RiskLevel, { headline: string; body: string; actionLabel: string }> = {
  Low: {
    headline: "Dengue activity is low in your area.",
    body: "Current surveillance data suggests dengue activity is within normal seasonal levels. Maintain routine prevention practices.",
    actionLabel: "Routine vigilance",
  },
  Moderate: {
    headline: "Dengue activity is moderate. Stay alert.",
    body: "Case counts are rising above seasonal baseline. Increase preventive measures and seek care early if you develop fever.",
    actionLabel: "Heightened vigilance",
  },
  High: {
    headline: "Dengue activity is elevated. Take action now.",
    body: "There is a confirmed surge in dengue cases in Dhaka South. Eliminate breeding sites immediately and seek care if symptomatic.",
    actionLabel: "Immediate prevention action",
  },
  Critical: {
    headline: "Dengue surge alert. Seek care at the first sign of fever.",
    body: "Dengue case counts are critically elevated. Do not wait for symptoms to worsen. Visit your nearest health facility immediately if you have fever.",
    actionLabel: "Urgent — seek care early",
  },
};

export default function PublicAdvisoryPreview({ forecast }: Props) {
  const sc = forecast.uncertainty_scenarios.expected_case;
  const riskMsg = RISK_MESSAGES[sc.risk_level];

  return (
    <div className="space-y-6 max-w-2xl">

      {/* ── Future-facing disclaimer ─────────────────────────────────── */}
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
        <Info className="h-5 w-5 text-amber-600 flex-shrink-0 mt-0.5" />
        <div className="text-sm text-amber-800 space-y-1">
          <p className="font-semibold">Future-Facing Simplified Advisory Layer</p>
          <p className="text-xs leading-relaxed">
            This is a preview of how DengueOps AI would communicate risk to
            general residents. The current prototype focuses on institutional
            preparedness for public health officials, hospital administrators,
            and emergency planners. A citizen-facing interface would be built
            as a separate simplified layer in production deployment.
          </p>
        </div>
      </div>

      {/* ── Audience badge ───────────────────────────────────────────── */}
      <div className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-4 py-2">
        <Users className="h-4 w-4 text-slate-500 flex-shrink-0" />
        <p className="text-xs text-slate-600">
          <span className="font-semibold text-slate-700">Intended audience:</span>{" "}
          Dhaka South residents, community health workers, and local media.
          No technical metrics are shown in this view.
        </p>
      </div>

      {/* ── Risk status card ─────────────────────────────────────────── */}
      <div
        className={`rounded-2xl border-2 p-6 shadow-sm ${
          sc.risk_level === "Critical"
            ? "border-red-300 bg-red-50"
            : sc.risk_level === "High"
            ? "border-orange-300 bg-orange-50"
            : sc.risk_level === "Moderate"
            ? "border-yellow-300 bg-yellow-50"
            : "border-emerald-300 bg-emerald-50"
        }`}
      >
        <div className="flex items-start gap-4">
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-2">
              <RiskBadge level={sc.risk_level} size="md" />
              <span
                className={`text-xs font-semibold uppercase tracking-wider ${
                  sc.risk_level === "Critical"
                    ? "text-red-700"
                    : sc.risk_level === "High"
                    ? "text-orange-700"
                    : sc.risk_level === "Moderate"
                    ? "text-yellow-700"
                    : "text-emerald-700"
                }`}
              >
                {riskMsg.actionLabel}
              </span>
            </div>
            <h2 className="text-lg font-bold text-slate-900 leading-snug">
              {riskMsg.headline}
            </h2>
            <p className="mt-2 text-sm text-slate-700 leading-relaxed">
              {riskMsg.body}
            </p>
          </div>
        </div>
      </div>

      {/* ── Prevention guidance ──────────────────────────────────────── */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-800 mb-4 flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-sky-600" />
          How to protect yourself and your family
        </h3>
        <ul className="space-y-3">
          {PREVENTION_STEPS.map((step, i) => (
            <li key={i} className="flex items-start gap-3 text-sm text-slate-700">
              <span className="flex-shrink-0 mt-0.5">{step.icon}</span>
              {step.text}
            </li>
          ))}
        </ul>
      </div>

      {/* ── When to seek care ────────────────────────────────────────── */}
      <div className="rounded-xl border border-red-100 bg-red-50 p-5 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-800 mb-4 flex items-center gap-2">
          <Stethoscope className="h-4 w-4 text-red-600" />
          When to seek care immediately
        </h3>
        <ul className="space-y-2">
          {SEEK_CARE_STEPS.map((step, i) => (
            <li key={i} className="flex items-start gap-2.5 text-sm text-slate-700">
              <CheckCircle2 className="h-4 w-4 text-red-500 flex-shrink-0 mt-0.5" />
              {step}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-xs text-slate-500 border-t border-red-200 pt-3">
          Nearest hospitals: Sir Salimullah Medical College Hospital (Mitford),
          Jatrabari General Hospital, Kamrangirchar Upazila Health Complex.
          For emergencies, call the IEDCR hotline: 16400.
        </p>
      </div>

      {/* ── No-metrics footer note ───────────────────────────────────── */}
      <div className="flex items-start gap-2 text-xs text-slate-400">
        <Info className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
        <p>
          This advisory is based on aggregate public health forecasting data.
          No individual patient information is used. For technical model
          details, switch to the Technical Validation tab.
        </p>
      </div>
    </div>
  );
}
