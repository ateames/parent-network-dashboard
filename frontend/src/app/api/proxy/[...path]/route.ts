import { NextRequest, NextResponse } from "next/server";

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

async function proxyRequest(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  try {
    const { path } = await context.params;
    if (!path?.length) {
      return NextResponse.json(
        { detail: "Proxy path is required" },
        { status: 400 },
      );
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
    return NextResponse.json({ detail: message }, { status: 502 });
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const HEAD = proxyRequest;
export const OPTIONS = proxyRequest;
