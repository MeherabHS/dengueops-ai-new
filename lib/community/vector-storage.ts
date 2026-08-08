import "server-only";

import { createHash, randomUUID } from "node:crypto";
import { mkdir, open, readFile, readdir } from "node:fs/promises";
import path from "node:path";
import type { VectorSubmissionMetadataV1, VectorSubmissionReceiptV1 } from "./contracts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TYPES = { "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp" } as const;
type ImageType = keyof typeof TYPES;

export class VectorStorageError extends Error {
  constructor(public readonly code: "image_too_large" | "invalid_image_type" | "invalid_metadata" | "not_found" | "storage_unavailable", public readonly status: number, message: string) { super(message); }
}

function root(): string {
  const resolved = path.resolve(process.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT?.trim() || path.join(process.cwd(), "local-uploads"));
  const publicRoot = path.resolve(process.cwd(), "public");
  if (resolved === publicRoot || resolved.startsWith(`${publicRoot}${path.sep}`)) throw new VectorStorageError("storage_unavailable", 503, "The configured upload storage is unsafe.");
  return resolved;
}

export function vectorImageMaxBytes(): number {
  const value = Number(process.env.DENGUEOPS_VECTOR_IMAGE_MAX_BYTES ?? 8 * 1024 * 1024);
  return Number.isSafeInteger(value) && value >= 1024 && value <= 25 * 1024 * 1024 ? value : 8 * 1024 * 1024;
}

export function detectImageType(bytes: Uint8Array): ImageType | null {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "image/jpeg";
  if (bytes.length >= 8 && [0x89,0x50,0x4e,0x47,0x0d,0x0a,0x1a,0x0a].every((value, index) => bytes[index] === value)) return "image/png";
  if (bytes.length >= 12 && Buffer.from(bytes.subarray(0, 4)).toString("ascii") === "RIFF" && Buffer.from(bytes.subarray(8, 12)).toString("ascii") === "WEBP") return "image/webp";
  return null;
}

function optionalNumber(value: FormDataEntryValue | null, minimum: number, maximum: number): number | null {
  if (value === null || value === "") return null;
  if (typeof value !== "string") throw new VectorStorageError("invalid_metadata", 400, "Submission metadata is invalid.");
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < minimum || parsed > maximum) throw new VectorStorageError("invalid_metadata", 400, "Submission metadata is invalid.");
  return parsed;
}

export function parseVectorMetadata(form: FormData): Pick<VectorSubmissionMetadataV1, "capturedAt" | "latitude" | "longitude" | "locationAccuracyM" | "note"> {
  const captured = form.get("capturedAt");
  const noteValue = form.get("note");
  if ((captured !== null && typeof captured !== "string") || (noteValue !== null && typeof noteValue !== "string")) throw new VectorStorageError("invalid_metadata", 400, "Submission metadata is invalid.");
  let capturedAt: string | null = null;
  if (captured !== null && captured !== "") {
    const parsed = new Date(captured);
    if (!Number.isFinite(parsed.getTime())) throw new VectorStorageError("invalid_metadata", 400, "Submission metadata is invalid.");
    capturedAt = parsed.toISOString();
  }
  const note = noteValue === null || noteValue.trim() === "" ? null : noteValue.trim();
  if (note && note.length > 500) throw new VectorStorageError("invalid_metadata", 400, "Submission metadata is invalid.");
  return { capturedAt, latitude: optionalNumber(form.get("latitude"), -90, 90), longitude: optionalNumber(form.get("longitude"), -180, 180), locationAccuracyM: optionalNumber(form.get("locationAccuracyM"), 0, 100_000), note };
}

export async function saveImage(bytes: Uint8Array, declaredType: string, metadata: ReturnType<typeof parseVectorMetadata>): Promise<VectorSubmissionReceiptV1> {
  if (bytes.byteLength > vectorImageMaxBytes()) throw new VectorStorageError("image_too_large", 413, "The image exceeds the configured upload limit.");
  const contentType = detectImageType(bytes);
  if (!contentType || contentType !== declaredType || !(declaredType in TYPES)) throw new VectorStorageError("invalid_image_type", 415, "Only JPEG, PNG, and WebP images are accepted.");
  const submissionId = randomUUID();
  const receivedAt = new Date().toISOString();
  const directory = path.join(root(), "submissions", submissionId);
  const storageKey = `submissions/${submissionId}/image${TYPES[contentType]}`;
  const record: VectorSubmissionMetadataV1 = { schemaVersion: "1.0", submissionId, receivedAt, contentType, byteSize: bytes.byteLength, sha256: createHash("sha256").update(bytes).digest("hex"), storageKey, status: "received", ...metadata };
  try {
    await mkdir(directory, { recursive: true });
    const image = await open(path.join(root(), storageKey), "wx");
    try { await image.writeFile(bytes); } finally { await image.close(); }
    const manifest = await open(path.join(directory, "metadata.json"), "wx");
    try { await manifest.writeFile(`${JSON.stringify(record, null, 2)}\n`, "utf8"); } finally { await manifest.close(); }
  } catch (error) {
    if (error instanceof VectorStorageError) throw error;
    throw new VectorStorageError("storage_unavailable", 503, "The image could not be stored.");
  }
  return { schemaVersion: "1.0", submissionId, status: "received", receivedAt };
}

function safeId(submissionId: string): void {
  if (!UUID.test(submissionId)) throw new VectorStorageError("not_found", 404, "The submission was not found.");
}

export async function readSubmission(submissionId: string): Promise<VectorSubmissionMetadataV1> {
  safeId(submissionId);
  try {
    const value = JSON.parse(await readFile(path.join(root(), "submissions", submissionId, "metadata.json"), "utf8")) as VectorSubmissionMetadataV1;
    if (value.submissionId !== submissionId || !value.storageKey.startsWith(`submissions/${submissionId}/`)) throw new Error("binding");
    return value;
  } catch (error) {
    if (error instanceof VectorStorageError) throw error;
    throw new VectorStorageError("not_found", 404, "The submission was not found.");
  }
}

export async function readImage(submissionId: string): Promise<{ metadata: VectorSubmissionMetadataV1; bytes: Buffer }> {
  const metadata = await readSubmission(submissionId);
  const resolved = path.resolve(root(), metadata.storageKey);
  const base = `${root()}${path.sep}`;
  if (!resolved.startsWith(base)) throw new VectorStorageError("not_found", 404, "The submission was not found.");
  try { return { metadata, bytes: await readFile(resolved) }; }
  catch { throw new VectorStorageError("not_found", 404, "The submission was not found."); }
}

export async function listSubmissions(limit = 25, cursor?: string): Promise<{ submissions: VectorSubmissionMetadataV1[]; nextCursor: string | null }> {
  const bounded = Math.min(50, Math.max(1, limit));
  let names: string[] = [];
  try { names = (await readdir(path.join(root(), "submissions"), { withFileTypes: true })).filter(item => item.isDirectory() && UUID.test(item.name)).map(item => item.name); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return { submissions: [], nextCursor: null }; throw new VectorStorageError("storage_unavailable", 503, "Submissions are unavailable."); }
  const records = (await Promise.all(names.map(name => readSubmission(name).catch(() => null))))
    .filter((item): item is VectorSubmissionMetadataV1 => item !== null)
    .sort((a, b) => b.receivedAt.localeCompare(a.receivedAt) || b.submissionId.localeCompare(a.submissionId));
  const start = cursor ? Math.max(0, records.findIndex(item => item.submissionId === cursor) + 1) : 0;
  const page = records.slice(start, start + bounded);
  return { submissions: page, nextCursor: records.length > start + bounded ? page.at(-1)!.submissionId : null };
}
