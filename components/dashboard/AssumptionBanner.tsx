import { Info } from "lucide-react";
import Link from "next/link";

export default function AssumptionBanner() {
  return (
    <div className="rounded-xl border border-sky-200 bg-sky-50 px-4 py-3 flex items-start gap-3">
      <Info className="h-5 w-5 text-sky-600 flex-shrink-0 mt-0.5" />
      <div>
        <p className="text-sm font-semibold text-sky-800">
          Methodology Assumption
        </p>
        <p className="text-xs text-sky-700 mt-0.5 leading-relaxed">
          Zone allocation uses a spatial exposure heuristic under city-level data constraints.
          Facility names and general bed-capacity figures use public/government references where available.
          Dengue bed allocation, occupancy, NS1/RDT stock, IV fluid stock, and consumption values are{" "}
          <span className="font-semibold">synthetic demonstration values</span>.
          Bed load uses an LOS approximation. Results are advisory only.{" "}
          <Link href="/assumptions" className="underline font-medium">
            Full assumptions & limitations →
          </Link>
        </p>
      </div>
    </div>
  );
}
