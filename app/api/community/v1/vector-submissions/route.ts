import { authenticateCommunityApi, communityApiErrorResponse } from "@/lib/community/api-auth";
import { parseVectorMetadata, saveImage, VectorStorageError, vectorImageMaxBytes } from "@/lib/community/vector-storage";

export const runtime = "nodejs";

function failure(error: unknown): Response {
  if (error instanceof VectorStorageError) return Response.json({ error: { code: error.code, message: error.message } }, { status: error.status, headers: { "Cache-Control": "no-store" } });
  return communityApiErrorResponse(error);
}

export async function POST(request: Request): Promise<Response> {
  try {
    authenticateCommunityApi(request, "vector:submit");
    const length = Number(request.headers.get("content-length"));
    if (Number.isFinite(length) && length > vectorImageMaxBytes() + 64 * 1024) throw new VectorStorageError("image_too_large", 413, "The image exceeds the configured upload limit.");
    let form: FormData;
    try { form = await request.formData(); }
    catch { return Response.json({ error: { code: "invalid_multipart", message: "A valid multipart form is required." } }, { status: 400, headers: { "Cache-Control": "no-store" } }); }
    const image = form.get("image");
    if (!(image instanceof File)) return Response.json({ error: { code: "image_required", message: "An image is required." } }, { status: 400, headers: { "Cache-Control": "no-store" } });
    const receipt = await saveImage(new Uint8Array(await image.arrayBuffer()), image.type, parseVectorMetadata(form));
    return Response.json(receipt, { status: 201, headers: { "Cache-Control": "no-store" } });
  } catch (error) { return failure(error); }
}
