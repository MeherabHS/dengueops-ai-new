import { AlertTriangle } from "lucide-react";

const LAG_RATIONALE = [
  {
    label: "Candidate 2-week lag",
    detail: "A provisional lookback used for research comparison; not proven optimal or causal for Dhaka.",
    weeks: "2 weeks",
  },
  {
    label: "Candidate 4-week lag",
    detail: "A second provisional lookback that requires local temporal backtesting.",
    weeks: "4 weeks",
  },
  {
    label: "Evidence status",
    detail: "No current lag is registered as a validated Dhaka epidemiological coefficient.",
    weeks: "missing",
  },
  {
    label: "Deployment status",
    detail: "These features remain candidate model inputs and must be selected using local data.",
    weeks: "research",
  },
];

const FEATURE_GROUPS = [
  {
    title: "Lagged Climate Features",
    color: "border-sky-200 bg-sky-50",
    badge: "bg-sky-100 text-sky-700",
    features: [
      { name: "rainfall_lag_2w",    desc: "Rainfall 14 days prior — provisional candidate" },
      { name: "rainfall_lag_4w",    desc: "Rainfall 28 days prior — provisional candidate" },
      { name: "temp_lag_2w",        desc: "Mean temperature 14 days prior" },
      { name: "temp_lag_4w",        desc: "Mean temperature 28 days prior" },
      { name: "humidity_lag_2w",    desc: "Humidity 14 days prior" },
      { name: "humidity_lag_4w",    desc: "Humidity 28 days prior" },
    ],
  },
  {
    title: "Case Trend Features",
    color: "border-indigo-200 bg-indigo-50",
    badge: "bg-indigo-100 text-indigo-700",
    features: [
      { name: "cases_lag_1w",       desc: "Cases last week — most recent signal" },
      { name: "cases_lag_2w",       desc: "Cases 2 weeks ago" },
      { name: "cases_lag_4w",       desc: "Cases 4 weeks ago" },
      { name: "cases_rolling_3w",   desc: "Rolling 3-week mean — short-term trend" },
      { name: "cases_rolling_4w",   desc: "Rolling 4-week mean — reference baseline" },
      { name: "cases_rolling_8w",   desc: "Rolling 8-week mean — medium-term context" },
      { name: "growth_rate_1w",     desc: "Week-over-week proportional change" },
      { name: "growth_rate_2w",     desc: "2-week proportional change" },
    ],
  },
  {
    title: "Seasonality Features",
    color: "border-amber-200 bg-amber-50",
    badge: "bg-amber-100 text-amber-700",
    features: [
      { name: "epi_week_sin",       desc: "Sine encoding of epi week (captures cyclical pattern)" },
      { name: "epi_week_cos",       desc: "Cosine encoding of epi week (captures cyclical phase)" },
      { name: "monsoon_flag",       desc: "Provisional configured calendar flag" },
      { name: "post_monsoon_flag",  desc: "Provisional configured calendar flag" },
    ],
  },
];

export default function FeatureEngineeringSection() {
  return (
    <section id="features" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Feature Engineering
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Lag-Aware Feature Engineering
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        The model uses prior observations to avoid future-data leakage. The 14- and 28-day
        climate lookbacks are governed candidate inputs; they are not established Dhaka
        epidemiological relationships and require local temporal backtesting.
      </p>

      {/* Lag rationale */}
      <div className="mb-8">
        <p className="text-sm font-semibold text-slate-700 mb-3">Governance of the current lag candidates</p>
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-sm">
          <div className="bg-slate-50 px-4 py-2 border-b border-slate-200">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Candidate feature configuration — locally unvalidated
            </p>
          </div>
          <div className="divide-y divide-slate-100">
            {LAG_RATIONALE.map((r, i) => (
              <div key={r.label} className="flex items-start gap-4 px-5 py-3">
                <div className="flex items-center justify-center w-6 h-6 rounded-full bg-sky-100 text-sky-700 text-xs font-bold flex-shrink-0 mt-0.5">
                  {i + 1}
                </div>
                <div className="flex-1">
                  <p className="text-xs font-semibold text-slate-800">{r.label}</p>
                  <p className="text-xs text-slate-500">{r.detail}</p>
                </div>
                <span className="rounded-full bg-sky-50 border border-sky-200 text-sky-700 px-2 py-0.5 text-[10px] font-mono flex-shrink-0">
                  {r.weeks}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Feature groups */}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3 mb-6">
        {FEATURE_GROUPS.map((group) => (
          <div key={group.title} className={`rounded-xl border ${group.color} p-4`}>
            <span className={`inline-block rounded-full px-2.5 py-0.5 text-[10px] font-semibold mb-3 ${group.badge}`}>
              {group.title}
            </span>
            <ul className="space-y-2">
              {group.features.map((f) => (
                <li key={f.name} className="flex flex-col">
                  <code className="text-[11px] font-mono font-semibold text-slate-800">{f.name}</code>
                  <span className="text-[10px] text-slate-500 leading-snug">{f.desc}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {/* Leakage prevention */}
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 px-5 py-4">
        <AlertTriangle className="h-4 w-4 text-amber-600 flex-shrink-0 mt-0.5" />
        <div>
          <p className="text-xs font-semibold text-amber-800 mb-1">Leakage prevention</p>
          <p className="text-xs text-amber-700 leading-relaxed">
            Rolling features are calculated using past values only —{" "}
            <code className="font-mono bg-amber-100 px-1 rounded">.shift(1)</code>{" "}
            is applied before all rolling windows. Target columns{" "}
            (<code className="font-mono bg-amber-100 px-1 rounded">target_cases_next_2w</code>) are excluded
            from <code className="font-mono bg-amber-100 px-1 rounded">FEATURE_COLUMNS</code>{" "}
            to prevent future data leakage. Train/test split is strictly chronological.
          </p>
        </div>
      </div>
    </section>
  );
}
