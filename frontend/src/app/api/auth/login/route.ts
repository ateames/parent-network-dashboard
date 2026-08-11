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

function requireServerEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing server-only env var ${name}`);
  }
  return value;
}

async function verifyViaBackend(
  username: string,
  password: string,
): Promise<string | null> {
  try {
    const base = requireServerEnv("BACKEND_URL").replace(/\/+$/, "");
    const token = requireServerEnv("ADMIN_TOKEN");
    const upstream = await fetch(`${base}/api/settings/dashboard/verify`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
    });
    if (!upstream.ok) return null;
    const body = (await upstream.json()) as { username?: string };
    return typeof body.username === "string" ? body.username : username;
  } catch {
    return null;
  }
}

function verifyViaEnv(username: string, password: string): string | null {
  const expected = dashboardCredentials();
  if (
    timingSafeEqualString(username, expected.username) &&
    timingSafeEqualString(password, expected.password)
  ) {
    return expected.username;
  }
  return null;
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

    if (!username || !password) {
      return NextResponse.json(
        { detail: "Invalid username or password" },
        { status: 401 },
      );
    }

    const verified =
      (await verifyViaBackend(username, password)) ??
      verifyViaEnv(username, password);

    if (!verified) {
      return NextResponse.json(
        { detail: "Invalid username or password" },
        { status: 401 },
      );
    }

    const token = await createSessionToken(verified);
    const response = NextResponse.json({
      ok: true,
      username: verified,
    });
    response.cookies.set(SESSION_COOKIE, token, sessionCookieOptions());
    return response;
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Login failed";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
