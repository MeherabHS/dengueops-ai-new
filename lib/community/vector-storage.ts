import "server-only";

import { createHash, randomUUID } from "node:crypto";
import { link, mkdir, open, readFile, readdir, rename, rm } from "node:fs/promises";
import path from "node:path";
import type {
  VectorAnalysisDispositionV1,
  VectorAnalyticalSubmissionV1,
  VectorDeletionTombstoneV1,
  VectorGovernanceReason,
  VectorSubmissionMetadataV1,
  VectorSubmissionReceiptV1,
} from "./contracts";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TYPES = { "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp" } as const;
type ImageType = keyof typeof TYPES;

export class VectorStorageError extends Error {
  constructor(public readonly code: "image_too_large" | "invalid_image_type" | "invalid_metadata" | "idempotency_conflict" | "submission_deleted" | "not_found" | "storage_unavailable", public readonly status: number, message: string) { super(message); }
}

function root(): string {
  const resolved = path.resolve(process.env.DENGUEOPS_COMMUNITY_UPLOAD_ROOT?.trim() || path.join(process.cwd(), "local-uploads"));
  const publicRoot = path.resolve(process.cwd(), "public");
  if (resolved === publicRoot || resolved.startsWith(`${publicRoot}${path.sep}`)) throw new VectorStorageError("storage_unavailable", 503, "The configured upload storage is unsafe.");
  return resolved;
}

function privatePath(...segments: string[]): string {
  const base = root();
  const resolved = path.resolve(base, ...segments);
  if (!resolved.startsWith(`${base}${path.sep}`)) throw new VectorStorageError("storage_unavailable", 503, "Vector storage is unavailable.");
  return resolved;
}

const INCLUDED: VectorAnalysisDispositionV1 = {
  status: "included",
  reason: null,
  note: null,
  changedAt: null,
  changedBy: null,
};

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

const JSON_NUMBER = /^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?$/;
const ISO_TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d{1,9})?(?:Z|[+-](\d{2}):(\d{2}))$/;
const SHA256 = /^[0-9a-f]{64}$/;
const GOVERNANCE_REASONS = new Set<VectorGovernanceReason>([
  "test_submission", "duplicate", "unusable_image", "invalid_location",
  "irrelevant_content", "user_request", "other",
]);

function invalidMetadata(): VectorStorageError {
  return new VectorStorageError("invalid_metadata", 400, "Submission metadata is invalid.");
}

function optionalNumber(value: FormDataEntryValue | null, minimum: number, maximum?: number): number | null {
  if (value === null || value === "") return null;
  if (typeof value !== "string" || !JSON_NUMBER.test(value)) throw invalidMetadata();
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < minimum || (maximum !== undefined && parsed > maximum)) throw invalidMetadata();
  return parsed;
}

function timestamp(value: string): string {
  const match = ISO_TIMESTAMP.exec(value);
  if (!match) throw invalidMetadata();
  const [year, month, day, hour, minute, second, offsetHour = 0, offsetMinute = 0] = match.slice(1).map(Number);
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (month < 1 || month > 12 || day < 1 || day > days[month - 1]
    || hour > 23 || minute > 59 || second > 59 || offsetHour > 23 || offsetMinute > 59) throw invalidMetadata();
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) throw invalidMetadata();
  return parsed.toISOString();
}

function isGovernanceReason(value: unknown): value is VectorGovernanceReason {
  return typeof value === "string" && GOVERNANCE_REASONS.has(value as VectorGovernanceReason);
}

async function publishExclusiveJson(target: string, value: unknown): Promise<boolean> {
  const stagingRoot = privatePath(".staging");
  const staged = path.join(stagingRoot, `${randomUUID()}.json`);
  await mkdir(stagingRoot, { recursive: true, mode: 0o700 });
  const file = await open(staged, "wx", 0o600);
  try { await file.writeFile(`${JSON.stringify(value, null, 2)}\n`, "utf8"); } finally { await file.close(); }
  try {
    await link(staged, target);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return false;
    throw error;
  } finally {
    await rm(staged, { force: true }).catch(() => undefined);
  }
}

export async function readDeletionTombstone(submissionId: string): Promise<VectorDeletionTombstoneV1 | null> {
  safeId(submissionId);
  try {
    const value = JSON.parse(await readFile(privatePath("tombstones", `${submissionId}.json`), "utf8")) as Record<string, unknown>;
    if (Object.keys(value).sort().join("|") !== "clientSubmissionId|deletedAt|deletedBy|deletionReason|originalEvidenceSha256|schemaVersion|submissionId"
      || value.schemaVersion !== "1.0" || value.submissionId !== submissionId
      || (value.clientSubmissionId !== null && !UUID.test(String(value.clientSubmissionId)))
      || typeof value.deletedAt !== "string" || !Number.isFinite(new Date(value.deletedAt).getTime())
      || typeof value.deletedBy !== "string" || !value.deletedBy
      || !isGovernanceReason(value.deletionReason)
      || typeof value.originalEvidenceSha256 !== "string" || !SHA256.test(value.originalEvidenceSha256)) throw new Error("invalid tombstone");
    return value as unknown as VectorDeletionTombstoneV1;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new VectorStorageError("storage_unavailable", 503, "Vector deletion evidence is unavailable.");
  }
}

async function readDisposition(submissionId: string): Promise<VectorAnalysisDispositionV1 | null> {
  try {
    const value = JSON.parse(await readFile(privatePath("submissions", submissionId, "analysis-disposition.json"), "utf8")) as Record<string, unknown>;
    if (Object.keys(value).sort().join("|") !== "changedAt|changedBy|note|reason|schemaVersion|status|submissionId"
      || value.schemaVersion !== "1.0" || value.submissionId !== submissionId || value.status !== "excluded"
      || !isGovernanceReason(value.reason) || (value.note !== null && typeof value.note !== "string")
      || typeof value.changedAt !== "string" || !Number.isFinite(new Date(value.changedAt).getTime())
      || typeof value.changedBy !== "string" || !value.changedBy) throw new Error("invalid disposition");
    return { status: "excluded", reason: value.reason, note: value.note as string | null, changedAt: value.changedAt, changedBy: value.changedBy };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw new VectorStorageError("storage_unavailable", 503, "Vector disposition evidence is unavailable.");
  }
}

export function parseVectorMetadata(form: FormData): Pick<VectorSubmissionMetadataV1, "clientSubmissionId" | "capturedAt" | "latitude" | "longitude" | "locationAccuracyM" | "note"> {
  const clientIdValue = form.get("clientSubmissionId");
  const captured = form.get("capturedAt");
  const noteValue = form.get("note");
  if ((clientIdValue !== null && typeof clientIdValue !== "string") || (captured !== null && typeof captured !== "string") || (noteValue !== null && typeof noteValue !== "string")) throw invalidMetadata();
  const clientSubmissionId = clientIdValue === null || clientIdValue === "" ? null : clientIdValue;
  if (clientSubmissionId !== null && !UUID.test(clientSubmissionId)) throw invalidMetadata();
  let capturedAt: string | null = null;
  if (captured !== null && captured !== "") {
    capturedAt = timestamp(captured);
  }
  const note = noteValue === null || noteValue.trim() === "" ? null : noteValue.trim();
  if (note && note.length > 500) throw invalidMetadata();
  const latitude = optionalNumber(form.get("latitude"), -90, 90);
  const longitude = optionalNumber(form.get("longitude"), -180, 180);
  const locationAccuracyM = optionalNumber(form.get("locationAccuracyM"), 0);
  if ((latitude === null) !== (longitude === null) || (locationAccuracyM !== null && latitude === null)) throw invalidMetadata();
  return { clientSubmissionId, capturedAt, latitude, longitude, locationAccuracyM, note };
}

export async function saveImage(bytes: Uint8Array, declaredType: string, metadata: ReturnType<typeof parseVectorMetadata>): Promise<VectorSubmissionReceiptV1> {
  if (bytes.byteLength > vectorImageMaxBytes()) throw new VectorStorageError("image_too_large", 413, "The image exceeds the configured upload limit.");
  const contentType = detectImageType(bytes);
  if (!contentType || contentType !== declaredType || !(declaredType in TYPES)) throw new VectorStorageError("invalid_image_type", 415, "Only JPEG, PNG, and WebP images are accepted.");
  const clientSubmissionId = metadata.clientSubmissionId ?? null;
  if (clientSubmissionId !== null && await readDeletionTombstone(clientSubmissionId)) {
    throw new VectorStorageError("submission_deleted", 410, "The logical submission was permanently deleted.");
  }
  const submissionId = clientSubmissionId ?? randomUUID();
  const receivedAt = new Date().toISOString();
  const directory = path.join(root(), "submissions", submissionId);
  const storageKey = `submissions/${submissionId}/image${TYPES[contentType]}`;
  const record: VectorSubmissionMetadataV1 = {
    schemaVersion: "1.0", submissionId, receivedAt, contentType, byteSize: bytes.byteLength,
    sha256: createHash("sha256").update(bytes).digest("hex"), storageKey, status: "received",
    analysisDisposition: { ...INCLUDED, changedAt: receivedAt, changedBy: "system:intake" },
    ...metadata, clientSubmissionId,
  };
  const stagingDirectory = path.join(root(), ".staging", randomUUID());
  try {
    await mkdir(path.join(root(), "submissions"), { recursive: true, mode: 0o700 });
    await mkdir(stagingDirectory, { recursive: true, mode: 0o700 });
    const image = await open(path.join(stagingDirectory, `image${TYPES[contentType]}`), "wx", 0o600);
    try { await image.writeFile(bytes); } finally { await image.close(); }
    const manifest = await open(path.join(stagingDirectory, "metadata.json"), "wx", 0o600);
    try { await manifest.writeFile(`${JSON.stringify(record, null, 2)}\n`, "utf8"); } finally { await manifest.close(); }
    try {
      await rename(stagingDirectory, directory);
      if (clientSubmissionId !== null && await readDeletionTombstone(clientSubmissionId)) {
        await retireActiveDirectory(submissionId);
        throw new VectorStorageError("submission_deleted", 410, "The logical submission was permanently deleted.");
      }
    } catch (error) {
      if (clientSubmissionId !== null) {
        if (await readDeletionTombstone(clientSubmissionId)) {
          throw new VectorStorageError("submission_deleted", 410, "The logical submission was permanently deleted.");
        }
        const existing = await readSubmission(submissionId).catch(() => null);
        if (existing) {
          const sameDelivery = existing.clientSubmissionId === clientSubmissionId
            && existing.contentType === record.contentType
            && existing.byteSize === record.byteSize
            && existing.sha256 === record.sha256
            && existing.capturedAt === record.capturedAt
            && existing.latitude === record.latitude
            && existing.longitude === record.longitude
            && existing.locationAccuracyM === record.locationAccuracyM
            && existing.note === record.note;
          if (sameDelivery) return { schemaVersion: "1.0", submissionId: existing.submissionId, status: "received", receivedAt: existing.receivedAt };
          throw new VectorStorageError("idempotency_conflict", 409, "The client submission identifier is already bound to different evidence.");
        }
        if (await readDeletionTombstone(clientSubmissionId)) {
          throw new VectorStorageError("submission_deleted", 410, "The logical submission was permanently deleted.");
        }
      }
      throw error;
    }
  } catch (error) {
    if (error instanceof VectorStorageError) throw error;
    throw new VectorStorageError("storage_unavailable", 503, "The image could not be stored.");
  } finally {
    await rm(stagingDirectory, { recursive: true, force: true }).catch(() => undefined);
  }
  return { schemaVersion: "1.0", submissionId, status: "received", receivedAt };
}

function safeId(submissionId: string): void {
  if (!UUID.test(submissionId)) throw new VectorStorageError("not_found", 404, "The submission was not found.");
}

function baseDisposition(value: unknown): VectorAnalysisDispositionV1 {
  if (!value || typeof value !== "object" || Array.isArray(value)) return { ...INCLUDED };
  const disposition = value as Record<string, unknown>;
  return disposition.status === "included" && disposition.reason === null && disposition.note === null
    && (disposition.changedAt === null || typeof disposition.changedAt === "string")
    && (disposition.changedBy === null || typeof disposition.changedBy === "string")
    ? disposition as unknown as VectorAnalysisDispositionV1
    : { ...INCLUDED };
}

async function readSubmissionRecord(submissionId: string): Promise<VectorSubmissionMetadataV1> {
  safeId(submissionId);
  try {
    const value = JSON.parse(await readFile(path.join(root(), "submissions", submissionId, "metadata.json"), "utf8")) as VectorSubmissionMetadataV1;
    const extension = TYPES[value.contentType as ImageType];
    if (value.submissionId !== submissionId || !extension || value.storageKey !== `submissions/${submissionId}/image${extension}`) throw new Error("binding");
    return { ...value, clientSubmissionId: value.clientSubmissionId ?? null, analysisDisposition: baseDisposition(value.analysisDisposition) };
  } catch (error) {
    if (error instanceof VectorStorageError) throw error;
    throw new VectorStorageError("not_found", 404, "The submission was not found.");
  }
}

export async function readSubmission(submissionId: string): Promise<VectorSubmissionMetadataV1> {
  safeId(submissionId);
  if (await readDeletionTombstone(submissionId)) throw new VectorStorageError("not_found", 404, "The submission was not found.");
  const metadata = await readSubmissionRecord(submissionId);
  return { ...metadata, analysisDisposition: await readDisposition(submissionId) ?? metadata.analysisDisposition };
}

export async function excludeSubmission(
  submissionId: string,
  reason: VectorGovernanceReason,
  note: string | null,
  changedBy: string,
): Promise<VectorSubmissionMetadataV1> {
  safeId(submissionId);
  if (!isGovernanceReason(reason) || (note !== null && (typeof note !== "string" || note.length > 500))
    || !changedBy.trim() || changedBy.length > 128) throw invalidMetadata();
  const current = await readSubmission(submissionId);
  if (current.analysisDisposition.status === "excluded") return current;
  const disposition = {
    schemaVersion: "1.0",
    submissionId,
    status: "excluded",
    reason,
    note,
    changedAt: new Date().toISOString(),
    changedBy,
  } as const;
  try {
    const created = await publishExclusiveJson(privatePath("submissions", submissionId, "analysis-disposition.json"), disposition);
    const persisted = created ? disposition : await readDisposition(submissionId);
    if (!persisted) throw new Error("missing disposition");
    if (await readDeletionTombstone(submissionId)) throw new VectorStorageError("not_found", 404, "The submission was not found.");
    return { ...current, analysisDisposition: {
      status: "excluded", reason: persisted.reason, note: persisted.note,
      changedAt: persisted.changedAt, changedBy: persisted.changedBy,
    } };
  } catch (error) {
    if (error instanceof VectorStorageError) throw error;
    throw new VectorStorageError("storage_unavailable", 503, "The analysis disposition could not be stored.");
  }
}

async function retireActiveDirectory(submissionId: string): Promise<void> {
  safeId(submissionId);
  const deletingRoot = privatePath(".deleting");
  const retired = privatePath(".deleting", `${submissionId}-${randomUUID()}`);
  await mkdir(deletingRoot, { recursive: true, mode: 0o700 });
  try {
    await rename(privatePath("submissions", submissionId), retired);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
    try {
      await readFile(privatePath("submissions", submissionId, "metadata.json"));
    } catch (readError) {
      if ((readError as NodeJS.ErrnoException).code === "ENOENT") return;
    }
    throw error;
  }
  await rm(retired, { recursive: true, force: true });
}

export async function deleteSubmission(
  submissionId: string,
  deletionReason: VectorGovernanceReason,
  deletedBy: string,
): Promise<{ status: "deleted" | "already_deleted"; tombstone: VectorDeletionTombstoneV1 }> {
  safeId(submissionId);
  if (!isGovernanceReason(deletionReason) || !deletedBy.trim() || deletedBy.length > 128) throw invalidMetadata();
  const prior = await readDeletionTombstone(submissionId);
  if (prior) {
    await retireActiveDirectory(submissionId);
    return { status: "already_deleted", tombstone: prior };
  }
  const metadata = await readSubmissionRecord(submissionId);
  const tombstone: VectorDeletionTombstoneV1 = {
    schemaVersion: "1.0",
    submissionId,
    clientSubmissionId: metadata.clientSubmissionId,
    deletedAt: new Date().toISOString(),
    deletedBy,
    deletionReason,
    originalEvidenceSha256: metadata.sha256,
  };
  try {
    await mkdir(privatePath("tombstones"), { recursive: true, mode: 0o700 });
    const created = await publishExclusiveJson(privatePath("tombstones", `${submissionId}.json`), tombstone);
    const persisted = created ? tombstone : await readDeletionTombstone(submissionId);
    if (!persisted) throw new Error("missing tombstone");
    await retireActiveDirectory(submissionId);
    return { status: created ? "deleted" : "already_deleted", tombstone: persisted };
  } catch (error) {
    if (error instanceof VectorStorageError) throw error;
    throw new VectorStorageError("storage_unavailable", 503, "The submission could not be permanently deleted.");
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

export function toVectorAnalyticalSubmission(metadata: VectorSubmissionMetadataV1): VectorAnalyticalSubmissionV1 | null {
  if (metadata.analysisDisposition?.status !== "included"
    || metadata.latitude === null || metadata.longitude === null
    || !Number.isFinite(metadata.latitude) || !Number.isFinite(metadata.longitude)
    || metadata.latitude < -90 || metadata.latitude > 90
    || metadata.longitude < -180 || metadata.longitude > 180
    || (metadata.locationAccuracyM !== null && (!Number.isFinite(metadata.locationAccuracyM) || metadata.locationAccuracyM < 0))) return null;
  return {
    submissionId: metadata.submissionId,
    clientSubmissionId: metadata.clientSubmissionId,
    latitude: metadata.latitude,
    longitude: metadata.longitude,
    accuracyMeters: metadata.locationAccuracyM,
    capturedAt: metadata.capturedAt,
    receivedAt: metadata.receivedAt,
    classificationStatus: "unreviewed",
    processingState: metadata.status,
    logicalObservationStatus: metadata.clientSubmissionId === null ? "legacy_unverified" : "client_id_bound",
    analysisDisposition: "included",
  };
}
