import { createHash } from "node:crypto";
import path from "node:path";
import { RuntimePublicError } from "./errors";

const CSV_MIME_TYPES = new Set([
  "text/csv",
  "application/csv",
  "application/vnd.ms-excel",
  "text/plain",
  "",
]);

export interface InspectedUpload {
  originalName: string;
  sizeBytes: number;
  sha256: string;
  bytes: Buffer;
  headers: string[];
  rowCount: number;
}

function safeOriginalName(name: string): string {
  const base = path.basename(name).replace(/[\u0000-\u001f\u007f<>:&]/g, "_").slice(0, 255);
  return base || "upload.csv";
}

function parseCsvShape(text: string): { headers: string[]; rowCount: number } {
  const records: string[][] = [];
  let record: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"' && field.length === 0) quoted = true;
    else if (char === ",") {
      record.push(field);
      field = "";
    } else if (char === "\n") {
      record.push(field.replace(/\r$/, ""));
      if (record.some((value) => value.length > 0)) records.push(record);
      record = [];
      field = "";
    } else field += char;
  }
  if (quoted) throw new RuntimePublicError("malformed_csv", "upload", "CSV contains an unterminated quoted field.", 400);
  record.push(field.replace(/\r$/, ""));
  if (record.some((value) => value.length > 0)) records.push(record);
  if (records.length === 0) throw new RuntimePublicError("empty_csv", "upload", "CSV must contain a header row.", 400);
  const headers = records[0].map((value) => value.trim());
  if (headers.length < 2 || !text.slice(0, text.indexOf("\n") === -1 ? text.length : text.indexOf("\n")).includes(",")) {
    throw new RuntimePublicError("unsupported_csv_delimiter", "upload", "Only comma-delimited CSV files are supported.", 400);
  }
  if (headers.some((value) => !value)) throw new RuntimePublicError("empty_csv_header", "upload", "CSV headers must be non-empty.", 400);
  const normalized = headers.map((value) => value.toLowerCase());
  if (new Set(normalized).size !== normalized.length) {
    throw new RuntimePublicError("duplicate_csv_header", "upload", "CSV contains duplicate headers.", 400);
  }
  const width = headers.length;
  if (records.slice(1).some((row) => row.length !== width)) {
    throw new RuntimePublicError("inconsistent_csv_width", "upload", "CSV rows must contain the same number of fields as the header.", 400);
  }
  return { headers, rowCount: records.length - 1 };
}

export async function inspectCsvUpload(file: File, maxBytes: number): Promise<InspectedUpload> {
  const originalName = safeOriginalName(file.name);
  if (path.extname(originalName).toLowerCase() !== ".csv") {
    throw new RuntimePublicError("invalid_file_extension", "upload", "Only .csv files are accepted.", 400);
  }
  if (!CSV_MIME_TYPES.has(file.type.toLowerCase())) {
    throw new RuntimePublicError("invalid_file_type", "upload", "The uploaded file is not a supported CSV media type.", 400);
  }
  if (file.size === 0) throw new RuntimePublicError("empty_upload", "upload", "Uploaded CSV files must not be empty.", 400);
  if (file.size > maxBytes) throw new RuntimePublicError("upload_too_large", "upload", "Each CSV must be within the configured upload limit.", 413);
  const bytes = Buffer.from(await file.arrayBuffer());
  if (bytes.includes(0)) throw new RuntimePublicError("nul_byte_detected", "upload", "CSV files must not contain NUL bytes.", 400);
  let text: string;
  try {
    text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new RuntimePublicError("invalid_utf8", "upload", "CSV files must use UTF-8 encoding.", 400);
  }
  text = text.replace(/^\uFEFF/, "");
  const disallowedControls = [...text].some((char) => {
    const code = char.charCodeAt(0);
    return code < 32 && char !== "\n" && char !== "\r" && char !== "\t";
  });
  if (disallowedControls) throw new RuntimePublicError("apparent_binary_input", "upload", "The uploaded file appears to contain binary data.", 400);
  const shape = parseCsvShape(text);
  return {
    originalName,
    sizeBytes: bytes.length,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    bytes,
    ...shape,
  };
}
