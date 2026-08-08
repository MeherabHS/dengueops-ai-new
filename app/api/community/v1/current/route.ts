import { authenticateCommunityApi, communityApiErrorResponse } from "@/lib/community/api-auth";
import { readCommunityCurrentV1 } from "@/lib/community/public-read-model";

export const runtime = "nodejs";

export async function GET(request: Request): Promise<Response> {
  try {
    authenticateCommunityApi(request, "community:read");
    return Response.json(await readCommunityCurrentV1(), { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    return communityApiErrorResponse(error);
  }
}
