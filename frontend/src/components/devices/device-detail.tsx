"use client";

import Link from "next/link";
import { ArrowLeft, RefreshCw } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";

import { ActivitySummaryPanel } from "@/components/activity/activity-summary-panel";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useDevice } from "@/hooks/use-device";
import {
  useCreateInternetRestriction,
  useDeleteInternetRestriction,
} from "@/hooks/use-internet-restriction";
import { usePatchDevice } from "@/hooks/use-patch-device";
import type {
  DeviceDetailOut,
  InternetRestrictionOut,
} from "@/lib/api/types";
import {
  deviceDisplayName,
  formatRelativeTime,
  identifierKindLabel,
  personRoleLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

const fieldClassName =
  "flex h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

const textareaClassName =
  "min-h-20 w-full rounded-lg border border-input bg-background px-2.5 py-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

function DetailLoading() {
  return (
    <div className="space-y-4" aria-busy="true" aria-live="polite">
      <div className="h-10 animate-pulse rounded-lg bg-muted" />
      <div className="h-36 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-40 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading device…</p>
    </div>
  );
}

function DetailError({
  message,
  onRetry,
  isFetching,
}: {
  message: string;
  onRetry: () => void;
  isFetching: boolean;
}) {
  return (
    <div
      className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-6"
      role="alert"
    >
      <p className="text-sm font-semibold text-destructive">
        Couldn’t load this device
      </p>
      <p className="mt-1 text-sm text-muted-foreground">{message}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-4"
        onClick={onRetry}
        disabled={isFetching}
      >
        <RefreshCw className="size-3.5" />
        {isFetching ? "Retrying…" : "Try again"}
      </Button>
    </div>
  );
}

function restrictionLabel(restriction: InternetRestrictionOut): string {
  if (restriction.expires_at) {
    return `Blocked until ${formatRelativeTime(restriction.expires_at)}`;
  }
  return "Blocked until re-enabled";
}

function InternetRestrictionPanel({ device }: { device: DeviceDetailOut }) {
  const create = useCreateInternetRestriction();
  const remove = useDeleteInternetRestriction();
  const [minutes, setMinutes] = useState("");
  const [confirming, setConfirming] = useState(false);
  const active = device.internet_restriction ?? null;

  useEffect(() => {
    setMinutes("");
    setConfirming(false);
  }, [device.id, active?.id]);

  function onDisable(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = minutes.trim();
    const parsed =
      trimmed.length === 0 ? null : Number.parseInt(trimmed, 10);
    if (parsed !== null && (!Number.isFinite(parsed) || parsed < 1)) {
      return;
    }
    create.mutate({
      deviceId: device.id,
      body: { minutes: parsed },
    });
  }

  if (active && active.status === "active") {
    return (
      <div className="space-y-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className="border-destructive/40 bg-destructive/10 text-destructive"
            >
              Internet disabled
            </Badge>
            <span className="text-sm text-muted-foreground">
              {restrictionLabel(active)}
            </span>
          </div>
          <p className="text-sm text-muted-foreground">
            UniFi client block for{" "}
            <span className="font-mono text-xs">{active.mac}</span>. This may
            also cut LAN access, not just the internet.
          </p>
          {active.error ? (
            <p className="text-sm text-destructive" role="alert">
              Last error: {active.error}
            </p>
          ) : null}
        </div>
        <Button
          type="button"
          size="sm"
          variant="default"
          disabled={remove.isPending}
          onClick={() => remove.mutate({ deviceId: device.id })}
        >
          {remove.isPending ? "Re-enabling…" : "Re-enable Internet"}
        </Button>
        {remove.isError ? (
          <p className="text-sm text-destructive" role="alert">
            {remove.error instanceof Error
              ? remove.error.message
              : "Couldn’t re-enable internet"}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <p className="text-sm text-muted-foreground">
        Blocks this device at UniFi (<code className="text-xs">block-sta</code>
        ). Leave minutes blank to disable indefinitely. Requires UniFi session
        auth.
      </p>
      {!confirming ? (
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setConfirming(true)}
        >
          Disable Internet
        </Button>
      ) : (
        <form onSubmit={onDisable} className="space-y-3">
          <div className="space-y-1.5">
            <label htmlFor="disable-minutes" className="text-sm font-medium">
              Minutes (optional)
            </label>
            <input
              id="disable-minutes"
              className={fieldClassName}
              inputMode="numeric"
              pattern="[0-9]*"
              min={1}
              placeholder="Blank = until re-enabled"
              value={minutes}
              onChange={(event) => setMinutes(event.target.value)}
              autoComplete="off"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" size="sm" disabled={create.isPending}>
              {create.isPending ? "Disabling…" : "Confirm disable"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={create.isPending}
              onClick={() => {
                setConfirming(false);
                setMinutes("");
              }}
            >
              Cancel
            </Button>
          </div>
          {create.isError ? (
            <p className="text-sm text-destructive" role="alert">
              {create.error instanceof Error
                ? create.error.message
                : "Couldn’t disable internet"}
            </p>
          ) : null}
        </form>
      )}
    </div>
  );
}

function DeviceEditForm({ device }: { device: DeviceDetailOut }) {
  const patch = usePatchDevice();
  const [displayName, setDisplayName] = useState(device.display_name ?? "");
  const [notes, setNotes] = useState(device.notes ?? "");

  useEffect(() => {
    setDisplayName(device.display_name ?? "");
    setNotes(device.notes ?? "");
  }, [device.display_name, device.notes, device.id]);

  const dirty =
    displayName.trim() !== (device.display_name ?? "").trim() ||
    notes !== (device.notes ?? "");

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextName = displayName.trim();
    patch.mutate({
      deviceId: device.id,
      patch: {
        display_name: nextName.length > 0 ? nextName : null,
        notes: notes.trim().length > 0 ? notes : null,
      },
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3 rounded-lg border p-4">
      <div className="space-y-1.5">
        <label htmlFor="device-display-name" className="text-sm font-medium">
          Display name
        </label>
        <input
          id="device-display-name"
          className={fieldClassName}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder={deviceDisplayName(device)}
          autoComplete="off"
        />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="device-notes" className="text-sm font-medium">
          Notes
        </label>
        <textarea
          id="device-notes"
          className={textareaClassName}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="Optional notes for this device"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={!dirty || patch.isPending}>
          {patch.isPending ? "Saving…" : "Save changes"}
        </Button>
        {dirty ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={patch.isPending}
            onClick={() => {
              setDisplayName(device.display_name ?? "");
              setNotes(device.notes ?? "");
            }}
          >
            Reset
          </Button>
        ) : null}
      </div>
      {patch.isError ? (
        <p className="text-sm text-destructive" role="alert">
          {patch.error instanceof Error
            ? patch.error.message
            : "Couldn’t save changes"}
        </p>
      ) : null}
      {patch.isSuccess && !dirty ? (
        <p className="text-xs text-muted-foreground" role="status">
          Saved
        </p>
      ) : null}
    </form>
  );
}

function IdentifiersList({ device }: { device: DeviceDetailOut }) {
  const identifiers = device.identifiers ?? [];
  if (identifiers.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
        No durable identifiers recorded yet.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {identifiers.map((identifier) => (
        <li
          key={identifier.id}
          className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">
                {identifierKindLabel(identifier.kind)}
              </Badge>
              <span className="text-xs text-muted-foreground tabular-nums">
                confidence {identifier.confidence}
              </span>
            </div>
            <p className="truncate font-mono text-sm">{identifier.value}</p>
          </div>
          <p className="shrink-0 text-xs text-muted-foreground">
            seen {formatRelativeTime(identifier.last_seen)}
          </p>
        </li>
      ))}
    </ul>
  );
}

function IpHistoryList({ device }: { device: DeviceDetailOut }) {
  const history = [...(device.ip_history ?? [])].reverse();
  if (history.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
        No IP history yet. Identity is keyed on MAC / UniFi id / hostname, not
        IP alone.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {history.map((row) => (
        <li
          key={row.id}
          className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="min-w-0 space-y-0.5">
            <p className="font-mono text-sm">{row.ip}</p>
            <p className="text-xs text-muted-foreground">
              {row.source}
              {row.observed_to == null ? " · current" : null}
            </p>
          </div>
          <p className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {formatRelativeTime(row.observed_from)}
            {row.observed_to
              ? ` → ${formatRelativeTime(row.observed_to)}`
              : " → now"}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function DeviceDetail({ deviceId }: { deviceId: string }) {
  const { data, error, isLoading, isError, isFetching, refetch } =
    useDevice(deviceId);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <Link
            href="/devices"
            className={cn(
              buttonVariants({ variant: "ghost", size: "sm" }),
              "-ml-2 w-fit",
            )}
          >
            <ArrowLeft className="size-3.5" />
            All devices
          </Link>
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              {data ? deviceDisplayName(data) : "Device"}
            </h1>
            {data ? (
              <div className="flex flex-wrap items-center gap-2">
                {data.is_unknown ? (
                  <Badge
                    variant="outline"
                    className="border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300"
                  >
                    Unknown
                  </Badge>
                ) : (
                  <Badge variant="secondary">Known</Badge>
                )}
                {data.internet_restriction?.status === "active" ? (
                  <Badge
                    variant="outline"
                    className="border-destructive/40 bg-destructive/10 text-destructive"
                  >
                    Internet disabled
                  </Badge>
                ) : null}
                {data.current_ip ? (
                  <span className="font-mono text-xs text-muted-foreground">
                    {data.current_ip}
                  </span>
                ) : (
                  <span className="text-xs text-muted-foreground">No current IP</span>
                )}
                <span className="text-xs text-muted-foreground">
                  Last seen {formatRelativeTime(data.last_seen)}
                </span>
              </div>
            ) : null}
          </div>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          disabled={isFetching || isLoading}
        >
          <RefreshCw className={cn("size-3.5", isFetching && "animate-spin")} />
          {isFetching ? "Refreshing…" : "Refresh"}
        </Button>
      </div>

      {isLoading ? <DetailLoading /> : null}

      {isError ? (
        <DetailError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {data ? (
        <>
          <section className="space-y-3">
            <div className="space-y-0.5">
              <h2 className="text-base font-semibold tracking-tight">
                Internet access
              </h2>
              <p className="text-sm text-muted-foreground">
                Temporarily or indefinitely block this device via UniFi.
              </p>
            </div>
            <InternetRestrictionPanel device={data} />
          </section>

          <section className="space-y-3">
            <div className="space-y-0.5">
              <h2 className="text-base font-semibold tracking-tight">
                Assigned person
              </h2>
              <p className="text-sm text-muted-foreground">
                Who this durable device identity currently belongs to.
              </p>
            </div>
            {data.assigned_person ? (
              <div className="flex flex-wrap items-center gap-2 rounded-lg border px-4 py-3">
                <Link
                  href={`/people?id=${encodeURIComponent(data.assigned_person.id)}`}
                  className="text-sm font-medium underline-offset-4 hover:underline"
                >
                  {data.assigned_person.name}
                </Link>
                <Badge variant="secondary">
                  {personRoleLabel(data.assigned_person.role)}
                </Badge>
              </div>
            ) : (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
                Unassigned. Link this device from a person detail page.
              </p>
            )}
          </section>

          <section className="space-y-3">
            <div className="space-y-0.5">
              <h2 className="text-base font-semibold tracking-tight">
                Display name & notes
              </h2>
              <p className="text-sm text-muted-foreground">
                Friendly labels stay local — they don’t change UniFi or Pi-hole.
              </p>
            </div>
            <DeviceEditForm device={data} />
          </section>

          <Separator />

          <section className="space-y-3">
            <div className="space-y-0.5">
              <h2 className="text-base font-semibold tracking-tight">
                Identifiers
              </h2>
              <p className="text-sm text-muted-foreground">
                Durable keys used for correlation — never IP alone.
              </p>
            </div>
            <IdentifiersList device={data} />
          </section>

          <section className="space-y-3">
            <div className="space-y-0.5">
              <h2 className="text-base font-semibold tracking-tight">
                IP history
              </h2>
              <p className="text-sm text-muted-foreground">
                Observed addresses over time as leases change.
              </p>
            </div>
            <IpHistoryList device={data} />
          </section>

          <Separator />

          <ActivitySummaryPanel subject={{ device: data.id }} />

          <p className="text-xs text-muted-foreground">
            First seen {formatRelativeTime(data.first_seen)} · logic{" "}
            {data.logic_version}
          </p>
        </>
      ) : null}
    </div>
  );
}
