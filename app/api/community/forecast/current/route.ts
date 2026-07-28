import { readPublicForecast } from "@/lib/community/public-read-model";

const headers = { "Cache-Control": "no-store" };

export async function GET() {
  try {
    return Response.json(await readPublicForecast(), { headers });
  } catch {
    return Response.json(
      { error: { code: "current_forecast_unavailable", message: "Current verified forecast information is unavailable." } },
      { status: 503, headers },
    );
  }
}
