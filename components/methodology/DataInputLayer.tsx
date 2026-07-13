import { Database, ShieldCheck } from "lucide-react";

const DATASETS = [
  {
    file: "dengue_cases.csv",
    purpose: "Weekly dengue case counts for time-series forecasting",
    fields: "epi_year, epi_week, city, total_cases",
    status: "Synthetic/demo aggregate data",
    color: "border-sky-200 bg-sky-50",
  },
  {
    file: "climate_data.csv",
    purpose: "Climate variables for lag-feature engineering",
    fields: "epi_year, epi_week, city, rainfall_mm, temp_mean_c, humidity_pct",
    status: "Synthetic/demo climate-style data",
    color: "border-indigo-200 bg-indigo-50",
  },
  {
    file: "zones.json",
    purpose: "Spatial exposure proxy parameters for zone-level allocation",
    fields: "zone_id, population_share, density_weight, vulnerability_weight, exposure_index",
    status: "Proxy exposure values — not validated geospatial data",
    color: "border-amber-200 bg-amber-50",
  },
  {
    file: "facilities.json",
    purpose: "Facility configuration for readiness and bed pressure modelling",
    fields: "facility_id, zone_id, facility_name, general_bed_capacity, dengue_bed_capacity_demo, avg_length_of_stay",
    status: "Real public anchors + synthetic readiness data",
    color: "border-orange-200 bg-orange-50",
  },
  {
    file: "inventory.json",
    purpose: "Supply stock and consumption for SDH simulation",
    fields: "facility_id, item_name, current_stock, baseline_daily_consumption, reorder_threshold_days",
    status: "Synthetic inventory values",
    color: "border-violet-200 bg-violet-50",
  },
];

const STATUS_TABLE = [
  {
    dataset: "Dengue cases",
    purpose: "Forecasting",
    prototype: "Synthetic/demo aggregate data",
    deployment: "Official aggregated DGHS/IEDCR surveillance reports",
  },
  {
    dataset: "Climate data",
    purpose: "Lagged environmental predictors",
    prototype: "Synthetic/demo climate-style data",
    deployment: "BMD / Open-Meteo / NASA POWER or approved meteorological source",
  },
  {
    dataset: "Zones",
    purpose: "Spatial exposure allocation",
    prototype: "Proxy exposure weight values",
    deployment: "Ward-level population, mobility, vector surveillance data",
  },
  {
    dataset: "Facilities",
    purpose: "Readiness modelling",
    prototype: "Real public anchors + synthetic readiness values",
    deployment: "Hospital/facility MIS — actual bed capacity and occupancy",
  },
  {
    dataset: "Inventory",
    purpose: "SDH simulation",
    prototype: "Synthetic inventory values",
    deployment: "Facility stock management or pharmacy system",
  },
];

export default function DataInputLayer() {
  return (
    <section id="data" className="mb-14">
      <p className="text-xs font-semibold uppercase tracking-wider text-sky-600 mb-2">
        Data Input Layer
      </p>
      <h2 className="text-2xl font-bold text-slate-900 mb-2">
        Input Datasets
      </h2>
      <p className="text-sm text-slate-500 max-w-2xl mb-8 leading-relaxed">
        Five structured data files feed the analytics pipeline.
        No patient-level records are used at any stage.
      </p>

      {/* Dataset cards */}
      <div className="space-y-3 mb-10">
        {DATASETS.map((d) => (
          <div key={d.file} className={`rounded-xl border ${d.color} px-5 py-4`}>
            <div className="flex flex-wrap items-start gap-4">
              <div className="flex-shrink-0">
                <Database className="h-4 w-4 text-slate-500 mt-0.5" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-bold font-mono text-slate-800 mb-0.5">{d.file}</p>
                <p className="text-xs text-slate-600 mb-1">{d.purpose}</p>
                <p className="text-[10px] font-mono text-slate-400">Fields: {d.fields}</p>
              </div>
              <span className="rounded-full border border-slate-300 bg-white px-2.5 py-0.5 text-[10px] font-semibold text-slate-600 flex-shrink-0">
                {d.status}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Status table */}
      <div>
        <p className="text-sm font-semibold text-slate-700 mb-3">
          Data Status: Prototype vs Real Deployment
        </p>
        <div className="rounded-xl border border-slate-200 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full text-xs">
              <thead className="bg-[#0f172a]">
                <tr>
                  {["Dataset", "Purpose", "Current Prototype Status", "Future Deployment Source"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left font-semibold text-sky-300 uppercase tracking-wider text-[10px] whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 bg-white">
                {STATUS_TABLE.map((row) => (
                  <tr key={row.dataset} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold text-slate-800">{row.dataset}</td>
                    <td className="px-4 py-3 text-slate-600">{row.purpose}</td>
                    <td className="px-4 py-3">
                      <span className="rounded-full bg-amber-100 text-amber-700 px-2 py-0.5 text-[10px] font-medium">
                        {row.prototype}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-500 italic">{row.deployment}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="mt-4 flex items-center gap-2 text-xs text-slate-500">
        <ShieldCheck className="h-4 w-4 text-emerald-500 flex-shrink-0" />
        <span>No patient-level data is used. All case counts are weekly aggregated totals at city or zone level.</span>
      </div>
    </section>
  );
}
