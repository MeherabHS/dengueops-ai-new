import { clsx } from "clsx";

interface FormulaCardProps {
  title: string;
  formula: string;
  variables?: { symbol: string; definition: string }[];
  note?: string;
  className?: string;
}

export default function FormulaCard({
  title,
  formula,
  variables,
  note,
  className,
}: FormulaCardProps) {
  return (
    <div className={clsx("rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden", className)}>
      <div className="bg-[#1e3a5f] px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-sky-300">{title}</p>
      </div>
      <div className="px-4 py-4">
        <div className="rounded-lg bg-slate-50 border border-slate-200 px-4 py-3 font-mono text-sm text-slate-800 leading-relaxed">
          {formula}
        </div>
        {variables && variables.length > 0 && (
          <div className="mt-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-2">
              Variable Definitions
            </p>
            <ul className="space-y-1.5">
              {variables.map((v) => (
                <li key={v.symbol} className="flex gap-2 text-sm">
                  <code className="text-sky-700 font-mono font-semibold shrink-0">{v.symbol}</code>
                  <span className="text-slate-600">{v.definition}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {note && (
          <p className="mt-3 text-xs text-slate-400 italic border-t border-slate-100 pt-3">
            {note}
          </p>
        )}
      </div>
    </div>
  );
}
