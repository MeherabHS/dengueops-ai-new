"use client";

import { useState, useRef } from "react";
import { Upload, CheckCircle2, XCircle, AlertTriangle, Download, Terminal, ChevronDown, ChevronUp } from "lucide-react";
import clsx from "clsx";

// ── Required column contracts ──────────────────────────────────────────────

const DENGUE_REQUIRED_COLUMNS = [
  "epi_year",
  "epi_week",
  "date_start",
  "city",
  "cases",
  "deaths",
  "source_type",
] as const;

const CLIMATE_REQUIRED_COLUMNS = [
  "epi_year",
  "epi_week",
  "date_start",
  "rainfall_mm",
  "avg_temp_c",
  "humidity_pct",
  "source_type",
] as const;

// ── CSV Templates ─────────────────────────────────────────────────────────

const DENGUE_TEMPLATE = [
  "epi_year,epi_week,date_start,city,cases,deaths,source_type",
  "2024,1,2024-01-01,Dhaka South,45,0,real_surveillance",
  "2024,2,2024-01-08,Dhaka South,48,0,real_surveillance",
].join("\n");

const CLIMATE_TEMPLATE = [
  "epi_year,epi_week,date_start,rainfall_mm,avg_temp_c,humidity_pct,source_type",
  "2024,1,2024-01-01,12.5,25.3,65.2,real_surveillance",
  "2024,2,2024-01-08,8.2,25.8,63.4,real_surveillance",
].join("\n");

// ── Types ─────────────────────────────────────────────────────────────────

interface ParseResult {
  fileName: string;
  rowCount: number;
  detectedColumns: string[];
  missingColumns: string[];
  isValid: boolean;
}

type FileKey = "dengue" | "climate";

// ── Pure CSV parsing (no dependencies) ───────────────────────────────────

/**
 * Extract header columns from a CSV string.
 * Handles quoted headers and trims whitespace.
 */
function parseCSVHeaders(text: string): string[] {
  const firstLine = text.split(/\r?\n/)[0] ?? "";
  return firstLine
    .split(",")
    .map((h) => h.trim().replace(/^["']|["']$/g, "").trim())
    .filter(Boolean);
}

/**
 * Count data rows (excluding header) in a CSV string.
 */
function parseCSVRowCount(text: string): number {
  const lines = text.trim().split(/\r?\n/);
  // Subtract 1 for header, filter empty trailing lines
  return Math.max(0, lines.filter((l) => l.trim() !== "").length - 1);
}

function validateFile(
  fileName: string,
  text: string,
  requiredColumns: readonly string[]
): ParseResult {
  const detectedColumns = parseCSVHeaders(text);
  const missingColumns = requiredColumns.filter(
    (col) => !detectedColumns.includes(col)
  );
  return {
    fileName,
    rowCount: parseCSVRowCount(text),
    detectedColumns,
    missingColumns,
    isValid: missingColumns.length === 0,
  };
}

// ── Template download helper ──────────────────────────────────────────────

function downloadTemplate(content: string, filename: string) {
  const blob = new Blob([content], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

// ── Sub-components ────────────────────────────────────────────────────────

function ValidationBadge({ isValid, missingCount }: { isValid: boolean; missingCount: number }) {
  if (isValid) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-700 border border-emerald-200">
        <CheckCircle2 className="h-3 w-3" />
        Schema valid
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700 border border-red-200">
      <XCircle className="h-3 w-3" />
      {missingCount} column{missingCount !== 1 ? "s" : ""} missing
    </span>
  );
}

function ParseResultCard({ result }: { result: ParseResult }) {
  return (
    <div
      className={clsx(
        "mt-3 rounded-lg border p-3 text-xs space-y-1.5",
        result.isValid
          ? "border-emerald-200 bg-emerald-50"
          : "border-red-200 bg-red-50"
      )}
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <span className="font-medium text-slate-700 truncate max-w-[200px]">
          {result.fileName}
        </span>
        <ValidationBadge isValid={result.isValid} missingCount={result.missingColumns.length} />
      </div>

      <p className="text-slate-600">
        <span className="font-medium">{result.rowCount.toLocaleString()}</span> data rows detected
      </p>

      <div>
        <p className="text-slate-500 mb-1">Detected columns ({result.detectedColumns.length}):</p>
        <div className="flex flex-wrap gap-1">
          {result.detectedColumns.map((col) => (
            <span
              key={col}
              className={clsx(
                "rounded px-1.5 py-0.5 font-mono text-[11px]",
                result.missingColumns.includes(col)
                  ? "bg-red-100 text-red-700"
                  : "bg-slate-100 text-slate-600"
              )}
            >
              {col}
            </span>
          ))}
        </div>
      </div>

      {result.missingColumns.length > 0 && (
        <div>
          <p className="text-red-600 font-medium mb-1">
            Missing required columns:
          </p>
          <div className="flex flex-wrap gap-1">
            {result.missingColumns.map((col) => (
              <span
                key={col}
                className="rounded bg-red-100 px-1.5 py-0.5 font-mono text-[11px] text-red-700 border border-red-200"
              >
                {col}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UploadZone({
  label,
  fileKey,
  requiredCols,
  result,
  onFile,
}: {
  label: string;
  fileKey: FileKey;
  requiredCols: readonly string[];
  result: ParseResult | null;
  onFile: (key: FileKey, result: ParseResult) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      onFile(fileKey, validateFile(file.name, text, requiredCols));
    };
    reader.readAsText(file);
  }

  return (
    <div>
      <p className="text-xs font-semibold text-slate-600 mb-1">{label}</p>
      <div
        className={clsx(
          "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-5 text-center transition-colors",
          result?.isValid
            ? "border-emerald-300 bg-emerald-50"
            : result && !result.isValid
            ? "border-red-300 bg-red-50"
            : "border-slate-300 bg-slate-50 hover:border-sky-400 hover:bg-sky-50"
        )}
        onClick={() => inputRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && inputRef.current?.click()}
        aria-label={`Upload ${label}`}
      >
        <Upload className="h-5 w-5 text-slate-400" />
        <p className="text-xs text-slate-500">
          {result ? (
            <span className="font-medium text-slate-700">{result.fileName}</span>
          ) : (
            <>Click to upload <span className="font-mono text-sky-600">.csv</span></>
          )}
        </p>
        <p className="text-[10px] text-slate-400">
          Required: {requiredCols.join(", ")}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,text/csv"
          className="hidden"
          onChange={handleChange}
        />
      </div>

      {result && <ParseResultCard result={result} />}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────

export default function CsvUploadPanel() {
  const [open, setOpen] = useState(false);
  const [results, setResults] = useState<Partial<Record<FileKey, ParseResult>>>({});

  function handleFile(key: FileKey, result: ParseResult) {
    setResults((prev) => ({ ...prev, [key]: result }));
  }

  const bothUploaded = results.dengue && results.climate;
  const bothValid = results.dengue?.isValid && results.climate?.isValid;

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
      {/* Collapsible header */}
      <button
        className="flex w-full items-center justify-between px-5 py-4 text-left hover:bg-slate-50 transition-colors"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <div className="flex items-center gap-2">
          <Upload className="h-4 w-4 text-sky-600" />
          <span className="text-sm font-semibold text-slate-800">
            Data Input Readiness
          </span>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
            CSV Validation
          </span>
        </div>
        {open ? (
          <ChevronUp className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        )}
      </button>

      {open && (
        <div className="border-t border-slate-200 px-5 py-5 space-y-6">
          {/* Purpose note */}
          <p className="text-xs text-slate-500 leading-relaxed">
            Upload your own CSV files to validate schema compatibility with the
            DengueOps AI analytics pipeline. Column structure is checked
            client-side — no data is sent to any server.
          </p>

          {/* Upload zones */}
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <UploadZone
              label="Dengue Cases CSV"
              fileKey="dengue"
              requiredCols={DENGUE_REQUIRED_COLUMNS}
              result={results.dengue ?? null}
              onFile={handleFile}
            />
            <UploadZone
              label="Climate Data CSV"
              fileKey="climate"
              requiredCols={CLIMATE_REQUIRED_COLUMNS}
              result={results.climate ?? null}
              onFile={handleFile}
            />
          </div>

          {/* Status summary */}
          {bothUploaded && (
            <div
              className={clsx(
                "flex items-start gap-3 rounded-lg p-3 text-xs border",
                bothValid
                  ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                  : "bg-yellow-50 border-yellow-200 text-yellow-800"
              )}
            >
              {bothValid ? (
                <CheckCircle2 className="h-4 w-4 mt-0.5 flex-shrink-0 text-emerald-600" />
              ) : (
                <AlertTriangle className="h-4 w-4 mt-0.5 flex-shrink-0 text-yellow-600" />
              )}
              <span>
                {bothValid
                  ? "Local header preview is complete. Governed runtime validation will be connected in P1.4."
                  : "Local header preview found missing columns. Governed runtime validation is not connected."}
              </span>
            </div>
          )}

          {/* Pipeline run button */}
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 space-y-2">
            <button
              disabled
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2.5 text-sm font-medium text-slate-400 cursor-not-allowed select-none"
              title="Full pipeline runs via the local Python analytics environment"
            >
              <Terminal className="h-4 w-4" />
              Runtime connector pending
            </button>
            <p className="text-[11px] text-slate-500 leading-relaxed text-center">
              In this prototype, full ML recalculation is executed via{" "}
              <code className="font-mono bg-slate-200 px-1 rounded">
                analytics/run_pipeline.py
              </code>
              . Browser upload currently validates readiness and previews data.
            </p>
          </div>

          {/* Template downloads */}
          <div>
            <p className="text-xs font-semibold text-slate-600 mb-2">
              CSV Template Downloads
            </p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => downloadTemplate(DENGUE_TEMPLATE, "dengue_cases_template.csv")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-700 hover:bg-sky-100 transition-colors"
              >
                <Download className="h-3.5 w-3.5" />
                Dengue CSV Template
              </button>
              <button
                onClick={() => downloadTemplate(CLIMATE_TEMPLATE, "climate_data_template.csv")}
                className="inline-flex items-center gap-1.5 rounded-lg border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs font-medium text-sky-700 hover:bg-sky-100 transition-colors"
              >
                <Download className="h-3.5 w-3.5" />
                Climate CSV Template
              </button>
            </div>
            <p className="mt-2 text-[11px] text-slate-400">
              Templates show required column names and example rows. Replace sample
              values with validated surveillance data before running the pipeline.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
