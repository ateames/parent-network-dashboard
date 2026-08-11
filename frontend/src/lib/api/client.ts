/**
 * Browser-facing API client.
 *
 * Always targets `/api/proxy/*`. The Next.js route handler forwards to the
 * FastAPI backend and attaches the admin token server-side. Never call the
 * backend URL or pass ADMIN_TOKEN from client code.
 */

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, message: string, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export type ApiFetchOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
  searchParams?: Record<string, string | number | boolean | undefined | null>;
};

function buildProxyUrl(
  path: string,
  searchParams?: ApiFetchOptions["searchParams"],
): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const url = new URL(`/api/proxy${normalized}`, "http://local.invalid");

  if (searchParams) {
    for (const [key, value] of Object.entries(searchParams)) {
      if (value === undefined || value === null) continue;
      url.searchParams.set(key, String(value));
    }
  }

  return `${url.pathname}${url.search}`;
}

/** Relative browser URL for `/api/proxy/*` (e.g. EventSource). */
export function apiProxyUrl(
  path: string,
  searchParams?: ApiFetchOptions["searchParams"],
): string {
  return buildProxyUrl(path, searchParams);
}

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { body, searchParams, headers, ...init } = options;
  const url = buildProxyUrl(path, searchParams);

  const requestHeaders = new Headers(headers);
  if (body !== undefined && !requestHeaders.has("Content-Type")) {
    requestHeaders.set("Content-Type", "application/json");
  }

  const response = await fetch(url, {
    ...init,
    headers: requestHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  });

  const contentType = response.headers.get("content-type") ?? "";
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    payload = contentType.includes("application/json")
      ? (JSON.parse(text) as unknown)
      : text;
  }

  if (!response.ok) {
    const message =
      typeof payload === "object" &&
      payload !== null &&
      "detail" in payload &&
      typeof (payload as { detail: unknown }).detail === "string"
        ? (payload as { detail: string }).detail
        : `Request failed with status ${response.status}`;
    throw new ApiError(response.status, message, payload);
  }

  return payload as T;
}
