import { NextResponse, type NextRequest } from "next/server";
import { sessionCookieName, verifySessionToken } from "@/lib/auth/session";

export async function proxy(request: NextRequest) {
  const session = await verifySessionToken(request.cookies.get(sessionCookieName())?.value);
  if (!session) {
    const signIn = request.nextUrl.clone();
    signIn.pathname = "/sign-in";
    signIn.searchParams.set("next", request.nextUrl.pathname);
    return NextResponse.redirect(signIn);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/forecast/:path*", "/validation/:path*"],
};
