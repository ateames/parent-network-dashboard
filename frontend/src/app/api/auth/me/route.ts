import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(): Promise<NextResponse> {
  try {
    const jar = await cookies();
    const session = await verifySessionToken(jar.get(SESSION_COOKIE)?.value);
    if (!session) {
      return NextResponse.json({ authenticated: false }, { status: 401 });
    }
    return NextResponse.json({
      authenticated: true,
      username: session.username,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Session check failed";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
