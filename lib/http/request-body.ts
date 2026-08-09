import "server-only";

export const DEFAULT_JSON_BODY_MAX_BYTES = 64 * 1024;

export class RequestBodyError extends Error {
  constructor(
    public readonly code: "invalid_request_body" | "request_body_too_large",
    public readonly status: 400 | 413,
    message: string,
  ) {
    super(message);
    this.name = "RequestBodyError";
  }
}

function declaredLength(request: Request): number | null {
  const raw = request.headers.get("content-length");
  if (raw === null) return null;
  if (!/^\d+$/.test(raw)) throw new RequestBodyError("invalid_request_body", 400, "The request body is invalid.");
  const value = Number(raw);
  if (!Number.isSafeInteger(value)) throw new RequestBodyError("invalid_request_body", 400, "The request body is invalid.");
  return value;
}

export async function readBoundedBody(request: Request, maximumBytes: number): Promise<Uint8Array> {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 1) throw new Error("invalid_request_body_limit");
  const length = declaredLength(request);
  if (length !== null && length > maximumBytes) {
    throw new RequestBodyError("request_body_too_large", 413, "The request body is too large.");
  }
  if (!request.body) return new Uint8Array();
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > maximumBytes) {
        await reader.cancel();
        throw new RequestBodyError("request_body_too_large", 413, "The request body is too large.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result;
}

export async function readBoundedJson<T = unknown>(
  request: Request,
  maximumBytes = DEFAULT_JSON_BODY_MAX_BYTES,
): Promise<T> {
  try {
    const bytes = await readBoundedBody(request, maximumBytes);
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as T;
  } catch (error) {
    if (error instanceof RequestBodyError) throw error;
    throw new RequestBodyError("invalid_request_body", 400, "The request body is invalid.");
  }
}

export async function readBoundedFormData(request: Request, maximumBytes: number): Promise<FormData> {
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.toLowerCase().startsWith("multipart/form-data;")) {
    throw new RequestBodyError("invalid_request_body", 400, "A valid multipart form is required.");
  }
  const bytes = await readBoundedBody(request, maximumBytes);
  const body = new ArrayBuffer(bytes.byteLength);
  new Uint8Array(body).set(bytes);
  try {
    return await new Request(request.url, {
      method: "POST",
      headers: { "content-type": contentType },
      body,
    }).formData();
  } catch {
    throw new RequestBodyError("invalid_request_body", 400, "A valid multipart form is required.");
  }
}
