import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, verifySessionToken } from "@/lib/auth/session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailers",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-length",
]);

/** Paths allowed without a dashboard session while first-run setup is incomplete. */
const SETUP_OPEN_PREFIXES = [
  "api/settings/setup-status",
  "api/settings/connections",
  "api/settings/dashboard/verify",
];

function requireServerEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(
      `Missing server-only env var ${name}. Set it in the frontend container / .env (never NEXT_PUBLIC_*).`,
    );
  }
  return value;
}

function backendBaseUrl(): string {
  return requireServerEnv("BACKEND_URL").replace(/\/+$/, "");
}

function adminToken(): string {
  return requireServerEnv("ADMIN_TOKEN");
}

function buildUpstreamUrl(pathSegments: string[], search: string): string {
  const path = pathSegments.map(encodeURIComponent).join("/");
  return `${backendBaseUrl()}/${path}${search}`;
}

function forwardRequestHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (HOP_BY_HOP_HEADERS.has(key.toLowerCase())) return;
    headers.set(key, value);
  });
  // Admin token stays server-side — never exposed to the browser bundle.
  headers.set("Authorization", `Bearer ${adminToken()}`);
  return headers;
}

function isSetupOpenPath(pathSegments: string[]): boolean {
  const joined = pathSegments.join("/");
  return SETUP_OPEN_PREFIXES.some(
    (prefix) => joined === prefix || joined.startsWith(`${prefix}/`),
  );
}

async function fetchSetupCompleted(): Promise<boolean> {
  try {
    const upstream = await fetch(
      `${backendBaseUrl()}/api/settings/setup-status`,
      {
        method: "GET",
        headers: { Authorization: `Bearer ${adminToken()}` },
        cache: "no-store",
      },
    );
    if (!upstream.ok) return true; // fail closed once stack is up but status errors
    const body = (await upstream.json()) as { setup_completed?: boolean };
    return Boolean(body.setup_completed);
  } catch {
    // Backend may still be starting during first boot — allow open paths.
    return false;
  }
}

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  try {
    const jar = await cookies();
    const session = await verifySessionToken(jar.get(SESSION_COOKIE)?.value);
    const { path } = await context.params;
    if (!path?.length) {
      return NextResponse.json(
        { detail: "Proxy path is required" },
        { status: 400 },
      );
    }

    if (!session) {
      const open = isSetupOpenPath(path);
      if (!open) {
        return NextResponse.json(
          { detail: "Authentication required" },
          { status: 401 },
        );
      }
      const completed = await fetchSetupCompleted();
      // After setup, only setup-status stays readable without a session.
      const joined = path.join("/");
      if (completed && joined !== "api/settings/setup-status") {
        return NextResponse.json(
          { detail: "Authentication required" },
          { status: 401 },
        );
      }
    }

    const upstreamUrl = buildUpstreamUrl(path, request.nextUrl.search);
    const method = request.method.toUpperCase();
    const hasBody = method !== "GET" && method !== "HEAD";

    const upstream = await fetch(upstreamUrl, {
      method,
      headers: forwardRequestHeaders(request),
      body: hasBody ? await request.arrayBuffer() : undefined,
      cache: "no-store",
      // Backend is on the LAN / Compose network only.
      redirect: "manual",
    });

    const responseHeaders = new Headers();
    upstream.headers.forEach((value, key) => {
      if (HOP_BY_HOP_HEADERS.has(key.toLowerCase())) return;
      responseHeaders.set(key, value);
    });

    return new NextResponse(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Proxy request failed";
    return new NextResponse(JSON.stringify({ detail: message }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const HEAD = proxyRequest;
export const OPTIONS = proxyRequest;
