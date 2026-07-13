"use client";

import { useRef, useState } from "react";
import { FileText, Upload, X } from "lucide-react";
import Button from "@/components/ui/Button";
import StatusBadge from "@/components/ui/StatusBadge";
import type { LocalFilePreview } from "@/lib/forecast-workflow-types";

const contracts = {
  dengue: ["epi_year", "epi_week", "date_start", "geography_level", "geography_id", "geography_name", "city", "cases", "deaths", "deaths_data_status", "source_type", "is_approximated", "approximation_method"],
  climate: ["epi_year", "epi_week", "date_start", "geography_level", "geography_id", "geography_name", "latitude", "longitude", "rainfall_mm", "avg_temp_c", "humidity_pct", "coverage_days", "source_type", "aggregation_method", "is_approximated"],
} as const;

function parse(file: File, key: "dengue" | "climate"): Promise<LocalFilePreview> {
  return file.text().then(text => {
    const lines = text.trim().split(/\r?\n/).filter(Boolean);
    const detectedColumns = (lines[0] ?? "").split(",").map(value => value.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
    return { key, file, detectedColumns, missingColumns: contracts[key].filter(column => !detectedColumns.includes(column)), approximateRowCount: Math.max(0, lines.length - 1), headerPreviewComplete: true };
  });
}

export default function DatasetUploadPanel({ kind, preview, onChange, onRemove }: { kind: "dengue" | "climate"; preview?: LocalFilePreview; onChange: (preview: LocalFilePreview) => void; onRemove: () => void }) {
  const input = useRef<HTMLInputElement>(null); const [dragging,setDragging] = useState(false);
  const label = kind === "dengue" ? "Dengue case data" : "Climate data";
  const accept = async (file?: File) => { if (file) onChange(await parse(file,kind)); };
  return <section className="rounded-xl border border-border-subtle bg-surface p-5 shadow-sm" aria-labelledby={`${kind}-upload-title`}>
    <div className="mb-4 flex items-start justify-between gap-3"><div><h2 id={`${kind}-upload-title`} className="font-semibold text-ink">{label}</h2><p className="mt-1 text-xs text-ink-muted">Local preview only. Authoritative checks occur only after you submit both files for server validation.</p></div><StatusBadge label="Local preview" variant="info" /></div>
    <label className={`flex min-h-40 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed p-5 text-center focus-within:ring-2 focus-within:ring-focus ${dragging ? "border-accent bg-accent/10" : "border-border-subtle bg-surface-muted"}`} onDragOver={e => {e.preventDefault(); setDragging(true)}} onDragLeave={() => setDragging(false)} onDrop={e => {e.preventDefault();setDragging(false);void accept(e.dataTransfer.files[0])}}>
      <Upload className="h-6 w-6 text-accent" aria-hidden="true" /><span className="mt-2 text-sm font-semibold text-ink">Choose a CSV or drop it here</span><span className="mt-1 text-xs text-ink-muted">Header names and approximate row count only</span>
      <input ref={input} className="sr-only" type="file" accept=".csv,text/csv" aria-label={`Choose ${label} CSV`} onChange={e => void accept(e.target.files?.[0])} />
    </label>
    {preview ? <div className="mt-4 rounded-lg border border-border-subtle bg-surface-muted p-4">
      <div className="flex items-start gap-3"><FileText className="mt-0.5 h-5 w-5 text-accent" /><div className="min-w-0 flex-1"><p className="truncate text-sm font-semibold text-ink">{preview.file.name}</p><p className="text-xs text-ink-muted">{(preview.file.size/1024).toFixed(1)} KB · approximately {preview.approximateRowCount} rows</p></div><button type="button" onClick={onRemove} className="rounded p-1 text-ink-muted hover:bg-surface focus-visible:ring-2 focus-visible:ring-focus" aria-label={`Remove ${label} file`}><X className="h-4 w-4" /></button></div>
      <p className="mt-3 text-xs text-ink-muted">Detected columns: {preview.detectedColumns.join(", ") || "none"}</p>
      <p className={`mt-1 text-xs ${preview.missingColumns.length ? "text-destructive" : "text-success"}`}>{preview.missingColumns.length ? `Missing headers: ${preview.missingColumns.join(", ")}` : "All expected headers are present. This is not governed validation."}</p>
      <Button className="mt-3" variant="secondary" onClick={() => input.current?.click()}>Replace file</Button>
    </div> : null}
  </section>;
}
