"use client";

import { FormEvent, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  useConnections,
  usePutConnections,
  useTestPihole,
  useTestUnifi,
} from "@/hooks/use-settings";
import type { ConnectionsOut, ConnectionsPutIn } from "@/lib/api/types";

const fieldClassName =
  "flex h-9 w-full rounded-lg border border-input bg-background px-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

const SECRET_PLACEHOLDER = "";

type ConnectionsFormProps = {
  /** When true, saving also sets setup_completed_at. */
  markSetupCompleteOnSave?: boolean;
  onSaved?: (connections: ConnectionsOut) => void;
  showDashboardFields?: boolean;
  showInstructions?: boolean;
  title?: string;
  description?: string;
};

type FormState = {
  pihole_url: string;
  pihole_auth_method: string;
  pihole_password: string;
  pihole_verify_tls: boolean;
  unifi_url: string;
  unifi_auth_method: string;
  unifi_username: string;
  unifi_password: string;
  unifi_token: string;
  unifi_site: string;
  unifi_verify_tls: boolean;
  dashboard_username: string;
  dashboard_password: string;
};

function fromConnections(data: ConnectionsOut): FormState {
  return {
    pihole_url: data.pihole_url || "",
    pihole_auth_method: data.pihole_auth_method || "password",
    pihole_password: SECRET_PLACEHOLDER,
    pihole_verify_tls: data.pihole_verify_tls,
    unifi_url: data.unifi_url || "",
    unifi_auth_method: data.unifi_auth_method || "session",
    unifi_username: data.unifi_username || "",
    unifi_password: SECRET_PLACEHOLDER,
    unifi_token: SECRET_PLACEHOLDER,
    unifi_site: data.unifi_site || "default",
    unifi_verify_tls: data.unifi_verify_tls,
    dashboard_username: data.dashboard_username || "admin",
    dashboard_password: SECRET_PLACEHOLDER,
  };
}

export function ConnectionsForm({
  markSetupCompleteOnSave = false,
  onSaved,
  showDashboardFields = true,
  showInstructions = true,
  title = "Connections",
  description = "Pi-hole and UniFi credentials are stored encrypted on this host. They are never kept in the browser after you save.",
}: ConnectionsFormProps) {
  const connections = useConnections();
  const put = usePutConnections();
  const testPihole = useTestPihole();
  const testUnifi = useTestUnifi();
  const [form, setForm] = useState<FormState | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (connections.data) {
      setForm(fromConnections(connections.data));
    }
  }, [connections.data]);

  if (connections.isLoading || !form) {
    return (
      <div className="h-48 animate-pulse rounded-lg bg-muted" aria-busy />
    );
  }

  if (connections.isError) {
    return (
      <div
        className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-6"
        role="alert"
      >
        <p className="text-sm font-semibold text-destructive">
          Couldn’t load connections
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {connections.error instanceof Error
            ? connections.error.message
            : "Request failed"}
        </p>
      </div>
    );
  }

  const data = connections.data!;

  function buildPayload(extra?: Partial<ConnectionsPutIn>): ConnectionsPutIn {
    const payload: ConnectionsPutIn = {
      pihole_url: form!.pihole_url.trim(),
      pihole_auth_method: form!.pihole_auth_method,
      pihole_verify_tls: form!.pihole_verify_tls,
      unifi_url: form!.unifi_url.trim(),
      unifi_auth_method: form!.unifi_auth_method,
      unifi_username: form!.unifi_username.trim(),
      unifi_site: form!.unifi_site.trim() || "default",
      unifi_verify_tls: form!.unifi_verify_tls,
      ...extra,
    };
    if (form!.pihole_password) {
      payload.pihole_password = form!.pihole_password;
    }
    if (form!.unifi_password) {
      payload.unifi_password = form!.unifi_password;
    }
    if (form!.unifi_token) {
      payload.unifi_token = form!.unifi_token;
    }
    if (showDashboardFields) {
      payload.dashboard_username = form!.dashboard_username.trim() || "admin";
      if (form!.dashboard_password) {
        payload.dashboard_password = form!.dashboard_password;
      }
    }
    return payload;
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    try {
      const saved = await put.mutateAsync(
        buildPayload(
          markSetupCompleteOnSave ? { mark_setup_complete: true } : undefined,
        ),
      );
      setMessage("Saved. The worker will pick up new credentials on the next poll.");
      setForm((prev) =>
        prev
          ? {
              ...prev,
              pihole_password: "",
              unifi_password: "",
              unifi_token: "",
              dashboard_password: "",
            }
          : prev,
      );
      onSaved?.(saved);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "Couldn’t save connections",
      );
    }
  }

  async function onTestPihole() {
    setMessage(null);
    const result = await testPihole.mutateAsync({
      url: form!.pihole_url.trim(),
      auth_method: form!.pihole_auth_method,
      password: form!.pihole_password || undefined,
      verify_tls: form!.pihole_verify_tls,
    });
    setMessage(result.message);
  }

  async function onTestUnifi() {
    setMessage(null);
    const result = await testUnifi.mutateAsync({
      url: form!.unifi_url.trim(),
      auth_method: form!.unifi_auth_method,
      username: form!.unifi_username.trim(),
      password: form!.unifi_password || undefined,
      token: form!.unifi_token || undefined,
      site: form!.unifi_site.trim() || "default",
      verify_tls: form!.unifi_verify_tls,
    });
    setMessage(result.message);
  }

  return (
    <form onSubmit={onSubmit} className="space-y-6 rounded-lg border p-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
        <p className="text-xs text-muted-foreground">
          Source: {data.source}
          {data.updated_at
            ? ` · last saved ${new Date(data.updated_at).toLocaleString()}`
            : ""}
        </p>
      </div>

      {showDashboardFields ? (
        <section className="space-y-3">
          <h3 className="text-sm font-semibold">Dashboard login</h3>
          <p className="text-sm text-muted-foreground">
            Optional override for the family admin password. Leave the password
            blank to keep the current value (install-time or previously saved).
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">Username</span>
              <input
                className={fieldClassName}
                value={form.dashboard_username}
                onChange={(event) =>
                  setForm((prev) =>
                    prev
                      ? { ...prev, dashboard_username: event.target.value }
                      : prev,
                  )
                }
                autoComplete="username"
              />
            </label>
            <label className="space-y-1.5 text-sm">
              <span className="font-medium">
                Password
                {data.dashboard_password_configured ? " (set)" : ""}
              </span>
              <input
                type="password"
                className={fieldClassName}
                value={form.dashboard_password}
                placeholder={
                  data.dashboard_password_configured
                    ? "Leave blank to keep"
                    : "Choose a password"
                }
                onChange={(event) =>
                  setForm((prev) =>
                    prev
                      ? { ...prev, dashboard_password: event.target.value }
                      : prev,
                  )
                }
                autoComplete="new-password"
              />
            </label>
          </div>
        </section>
      ) : null}

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">Pi-hole</h3>
        {showInstructions ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            <li>Use the Pi-hole admin web password (v6 SID auth).</li>
            <li>
              Prefer a LAN IP (for example <code>http://192.168.1.2</code>) —
              <code>.local</code> names are often unreliable from Docker.
            </li>
            <li>This dashboard only reads DNS query history — it never changes blocklists.</li>
          </ul>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm sm:col-span-2">
            <span className="font-medium">URL</span>
            <input
              className={fieldClassName}
              value={form.pihole_url}
              placeholder="http://192.168.1.2"
              onChange={(event) =>
                setForm((prev) =>
                  prev ? { ...prev, pihole_url: event.target.value } : prev,
                )
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">Auth method</span>
            <select
              className={fieldClassName}
              value={form.pihole_auth_method}
              onChange={(event) =>
                setForm((prev) =>
                  prev
                    ? { ...prev, pihole_auth_method: event.target.value }
                    : prev,
                )
              }
            >
              <option value="password">password (v6)</option>
              <option value="token">token (legacy)</option>
              <option value="none">none</option>
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">
              Password
              {data.pihole_password_configured ? " (set)" : ""}
            </span>
            <input
              type="password"
              className={fieldClassName}
              value={form.pihole_password}
              placeholder={
                data.pihole_password_configured
                  ? "Leave blank to keep"
                  : "Pi-hole admin password"
              }
              onChange={(event) =>
                setForm((prev) =>
                  prev
                    ? { ...prev, pihole_password: event.target.value }
                    : prev,
                )
              }
              autoComplete="off"
            />
          </label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={form.pihole_verify_tls}
              onChange={(event) =>
                setForm((prev) =>
                  prev
                    ? { ...prev, pihole_verify_tls: event.target.checked }
                    : prev,
                )
              }
            />
            Verify TLS certificate
          </label>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => void onTestPihole()}
          disabled={testPihole.isPending}
        >
          {testPihole.isPending ? "Testing…" : "Test Pi-hole"}
        </Button>
      </section>

      <section className="space-y-3">
        <h3 className="text-sm font-semibold">UniFi</h3>
        {showInstructions ? (
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
            <li>
              For <strong>Disable Internet</strong>, use{" "}
              <code>session</code> with a local UniFi OS admin
              username/password (not a Network “user”). Token mode cannot
              block or unblock clients.
            </li>
            <li>
              For read-only ingest only, API key auth works: create a key
              under UniFi OS <strong>Control Plane → Integrations</strong>,
              then choose <code>token</code> below.
            </li>
            <li>
              Use <code>https://&lt;gateway-lan-ip&gt;</code> (not{" "}
              <code>http://</code>). Leave TLS verify off for self-signed certs.
            </li>
            <li>
              Site can be <code>default</code>, the display name (for example{" "}
              <code>Teames-house</code>), or the site UUID — token auth resolves
              it via the Integration API.
            </li>
            <li>
              Allowed UniFi writes: client block/unblock only. Pi-hole is never
              modified.
            </li>
          </ul>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm sm:col-span-2">
            <span className="font-medium">URL</span>
            <input
              className={fieldClassName}
              value={form.unifi_url}
              placeholder="https://192.168.1.1"
              onChange={(event) =>
                setForm((prev) =>
                  prev ? { ...prev, unifi_url: event.target.value } : prev,
                )
              }
            />
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">Auth method</span>
            <select
              className={fieldClassName}
              value={form.unifi_auth_method}
              onChange={(event) =>
                setForm((prev) =>
                  prev
                    ? { ...prev, unifi_auth_method: event.target.value }
                    : prev,
                )
              }
            >
              <option value="session">session (username/password)</option>
              <option value="token">token (API key)</option>
            </select>
          </label>
          <label className="space-y-1.5 text-sm">
            <span className="font-medium">Site</span>
            <input
              className={fieldClassName}
              value={form.unifi_site}
              onChange={(event) =>
                setForm((prev) =>
                  prev ? { ...prev, unifi_site: event.target.value } : prev,
                )
              }
            />
          </label>
          {form.unifi_auth_method === "token" ? (
            <label className="space-y-1.5 text-sm sm:col-span-2">
              <span className="font-medium">
                API key
                {data.unifi_token_configured ? " (set)" : ""}
              </span>
              <input
                type="password"
                className={fieldClassName}
                value={form.unifi_token}
                placeholder={
                  data.unifi_token_configured
                    ? "Leave blank to keep"
                    : "UniFi API key"
                }
                onChange={(event) =>
                  setForm((prev) =>
                    prev
                      ? { ...prev, unifi_token: event.target.value }
                      : prev,
                  )
                }
                autoComplete="off"
              />
            </label>
          ) : (
            <>
              <label className="space-y-1.5 text-sm">
                <span className="font-medium">Username</span>
                <input
                  className={fieldClassName}
                  value={form.unifi_username}
                  onChange={(event) =>
                    setForm((prev) =>
                      prev
                        ? { ...prev, unifi_username: event.target.value }
                        : prev,
                    )
                  }
                  autoComplete="off"
                />
              </label>
              <label className="space-y-1.5 text-sm">
                <span className="font-medium">
                  Password
                  {data.unifi_password_configured ? " (set)" : ""}
                </span>
                <input
                  type="password"
                  className={fieldClassName}
                  value={form.unifi_password}
                  placeholder={
                    data.unifi_password_configured
                      ? "Leave blank to keep"
                      : "UniFi password"
                  }
                  onChange={(event) =>
                    setForm((prev) =>
                      prev
                        ? { ...prev, unifi_password: event.target.value }
                        : prev,
                    )
                  }
                  autoComplete="off"
                />
              </label>
            </>
          )}
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input
              type="checkbox"
              checked={form.unifi_verify_tls}
              onChange={(event) =>
                setForm((prev) =>
                  prev
                    ? { ...prev, unifi_verify_tls: event.target.checked }
                    : prev,
                )
              }
            />
            Verify TLS certificate
          </label>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => void onTestUnifi()}
          disabled={testUnifi.isPending}
        >
          {testUnifi.isPending ? "Testing…" : "Test UniFi"}
        </Button>
      </section>

      {showInstructions && data.syslog_enabled ? (
        <section className="space-y-2 rounded-md bg-muted/40 p-3 text-sm">
          <h3 className="font-semibold">UniFi syslog (recommended)</h3>
          <p className="text-muted-foreground">
            In the UniFi Network app, enable remote logging / syslog / SIEM and
            point it at this Pi’s LAN IP on port{" "}
            <strong>{data.syslog_port}</strong> (UDP). Exact menus vary by
            version — see docs/unifi-syslog.md. No credentials are required for
            syslog; traffic is one-way into this dashboard.
          </p>
        </section>
      ) : null}

      {message ? (
        <p
          className={`text-sm ${
            message.toLowerCase().includes("fail") ||
            message.toLowerCase().includes("couldn’t") ||
            message.toLowerCase().includes("error")
              ? "text-destructive"
              : "text-muted-foreground"
          }`}
          role="status"
        >
          {message}
        </p>
      ) : null}

      <Button type="submit" disabled={put.isPending}>
        {put.isPending
          ? "Saving…"
          : markSetupCompleteOnSave
            ? "Save and finish setup"
            : "Save connections"}
      </Button>
    </form>
  );
}
