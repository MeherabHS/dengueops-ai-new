import { ShieldCheck } from "lucide-react";
import Link from "next/link";

export default function EthicsBanner() {
  return (
    <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 flex items-start gap-3">
      <ShieldCheck className="h-5 w-5 text-emerald-600 flex-shrink-0 mt-0.5" />
      <div>
        <p className="text-sm font-semibold text-emerald-800">
          Data & Ethics Notice
        </p>
        <p className="text-xs text-emerald-700 mt-0.5 leading-relaxed">
          Prototype uses aggregated/synthetic data only. No patient-level data is collected or
          processed. This system is advisory only — all preparedness decisions require qualified
          public health professional review.{" "}
          <Link href="/ethics" className="underline font-medium">
            Read full ethics statement →
          </Link>
        </p>
      </div>
    </div>
  );
}
