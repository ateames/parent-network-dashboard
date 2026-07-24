import { NextRequest, NextResponse } from "next/server";

import {
  SESSION_COOKIE,
  createSessionToken,
  dashboardCredentials,
  sessionCookieOptions,
} from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function timingSafeEqualString(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  try {
    const body = (await request.json()) as {
      username?: unknown;
      password?: unknown;
    };
    const username =
      typeof body.username === "string" ? body.username.trim() : "";
    const password = typeof body.password === "string" ? body.password : "";

    const expected = dashboardCredentials();
    if (
      !username ||
      !password ||
      !timingSafeEqualString(username, expected.username) ||
      !timingSafeEqualString(password, expected.password)
    ) {
      return NextResponse.json(
        { detail: "Invalid username or password" },
        { status: 401 },
      );
    }

    const token = await createSessionToken(expected.username);
    const response = NextResponse.json({
      ok: true,
      username: expected.username,
    });
    response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions());
    return response;
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Login failed";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
