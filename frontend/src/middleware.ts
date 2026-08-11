import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth/session";

const PUBLIC_PATHS = new Set(["/login", "/setup"]);

/** Proxy paths the setup wizard may call before login (proxy enforces setup gate). */
const PUBLIC_PROXY_PREFIXES = [
  "/api/proxy/api/settings/setup-status",
  "/api/proxy/api/settings/connections",
  "/api/proxy/api/settings/dashboard/verify",
];

function isPublic(pathname: string): boolean {
  if (PUBLIC_PATHS.has(pathname)) return true;
  if (pathname.startsWith("/api/auth/")) return true;
  if (PUBLIC_PROXY_PREFIXES.some((prefix) => pathname.startsWith(prefix))) {
    return true;
  }
  if (pathname.startsWith("/_next/")) return true;
  if (pathname === "/favicon.ico") return true;
  return false;
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (isPublic(pathname)) {
    if (pathname === "/login") {
      const session = await verifySessionToken(
        request.cookies.get(SESSION_COOKIE)?.value,
      );
      if (session) {
        return NextResponse.redirect(new URL("/overview", request.url));
      }
    }
    return NextResponse.next();
  }

  const session = await verifySessionToken(
    request.cookies.get(SESSION_COOKIE)?.value,
  );
  if (!session) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json(
        { detail: "Authentication required" },
        { status: 401 },
      );
    }
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("next", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
