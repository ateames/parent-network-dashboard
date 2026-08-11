/**
 * Signed dashboard session cookie (UI gate only).
 * Backend ADMIN_TOKEN stays server-side in the API proxy — never put in this cookie.
 *
 * Uses Web Crypto so verification works in Edge middleware and Node route handlers.
 */

export const SESSION_COOKIE = "pnd_session";
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 7; // 7 days

export type SessionPayload = {
  username: string;
  exp: number;
};

function requireEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(
      `Missing server-only env var ${name}. See docs/local-auth.md.`,
    );
  }
  return value;
}

export function dashboardCredentials(): { username: string; password: string } {
  return {
    username: requireEnv("DASHBOARD_USERNAME"),
    password: requireEnv("DASHBOARD_PASSWORD"),
  };
}

function sessionSecret(): string {
  return requireEnv("DASHBOARD_SESSION_SECRET");
}

function bytesToBase64Url(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  let binary = "";
  for (let i = 0; i < view.length; i += 1) {
    binary += String.fromCharCode(view[i]!);
  }
  const b64 =
    typeof btoa === "function"
      ? btoa(binary)
      : Buffer.from(binary, "binary").toString("base64");
  return b64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function base64UrlToBytes(value: string): Uint8Array {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/");
  const pad = padded.length % 4 === 0 ? "" : "=".repeat(4 - (padded.length % 4));
  const b64 = padded + pad;
  const binary =
    typeof atob === "function"
      ? atob(b64)
      : Buffer.from(b64, "base64").toString("binary");
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    out[i] = binary.charCodeAt(i);
  }
  return out;
}

function utf8ToBytes(value: string): Uint8Array {
  return new TextEncoder().encode(value);
}

function bytesToUtf8(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes);
}

function timingSafeEqualBytes(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a[i]! ^ b[i]!;
  }
  return diff === 0;
}

async function sign(body: string): Promise<string> {
  const secretBytes = utf8ToBytes(sessionSecret());
  const bodyBytes = utf8ToBytes(body);
  const key = await crypto.subtle.importKey(
    "raw",
    secretBytes.buffer.slice(
      secretBytes.byteOffset,
      secretBytes.byteOffset + secretBytes.byteLength,
    ) as ArrayBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    bodyBytes.buffer.slice(
      bodyBytes.byteOffset,
      bodyBytes.byteOffset + bodyBytes.byteLength,
    ) as ArrayBuffer,
  );
  return bytesToBase64Url(signature);
}

export async function createSessionToken(
  username: string,
  now = Date.now(),
): Promise<string> {
  const payload: SessionPayload = {
    username,
    exp: Math.floor(now / 1000) + SESSION_TTL_SECONDS,
  };
  const body = bytesToBase64Url(utf8ToBytes(JSON.stringify(payload)));
  const signature = await sign(body);
  return `${body}.${signature}`;
}

export async function verifySessionToken(
  token: string | undefined | null,
  now = Date.now(),
): Promise<SessionPayload | null> {
  if (!token) return null;
  const [body, signature] = token.split(".");
  if (!body || !signature) return null;
  try {
    const expected = await sign(body);
    const a = base64UrlToBytes(signature);
    const b = base64UrlToBytes(expected);
    if (!timingSafeEqualBytes(a, b)) return null;
    const payload = JSON.parse(bytesToUtf8(base64UrlToBytes(body))) as SessionPayload;
    if (
      typeof payload.username !== "string" ||
      typeof payload.exp !== "number"
    ) {
      return null;
    }
    if (payload.exp * 1000 <= now) return null;
    return payload;
  } catch {
    return null;
  }
}

/**
 * LAN dashboards are typically served over plain HTTP.
 * Default Secure=false so browsers accept the cookie on http://<pi-ip>:3000.
 * Set DASHBOARD_COOKIE_SECURE=true only when terminating TLS in front of the UI.
 */
export function sessionCookieSecure(): boolean {
  const raw = process.env.DASHBOARD_COOKIE_SECURE?.trim().toLowerCase();
  if (raw === "true" || raw === "1" || raw === "yes") return true;
  if (raw === "false" || raw === "0" || raw === "no") return false;
  return false;
}

export function sessionCookieOptions(maxAge = SESSION_TTL_SECONDS) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    secure: sessionCookieSecure(),
    path: "/",
    maxAge,
  };
}
