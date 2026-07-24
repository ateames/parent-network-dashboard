"use client";

import Link from "next/link";
import { Radio, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  type LiveConnectionStatus,
  useLiveEvents,
} from "@/hooks/use-live-events";
import type { FindingSeverity, StreamEvent } from "@/lib/api/types";
import {
  formatRelativeTime,
  severityLabel,
  sourceLabel,
  streamEventKindLabel,
} from "@/lib/format";
import { LIVE_EVENT_CAP } from "@/lib/live-events";
import { cn } from "@/lib/utils";

function connectionCopy(status: LiveConnectionStatus): {
  label: string;
  tone: string;
} {
  switch (status) {
    case "live":
      return {
        label: "Live",
        tone: "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300",
      };
    case "reconnecting":
      return {
        label: "Reconnecting…",
        tone: "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-300",
      };
    case "connecting":
      return {
        label: "Connecting…",
        tone: "border-border bg-muted/40 text-muted-foreground",
      };
  }
}

function severityTone(severity: FindingSeverity): string {
  switch (severity) {
    case "high":
      return "border-red-500/40 bg-red-500/10 text-red-800 dark:text-red-300";
    case "medium":
      return "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-300";
    case "low":
      return "border-border bg-muted/50 text-foreground";
    case "info":
    default:
      return "border-border bg-background text-muted-foreground";
  }
}

function eventRowTone(severity: FindingSeverity): string {
  switch (severity) {
    case "high":
      return "border-l-red-500/70 bg-red-500/[0.04]";
    case "medium":
      return "border-l-amber-500/70 bg-amber-500/[0.04]";
    case "low":
      return "border-l-border bg-muted/20";
    case "info":
    default:
      return "border-l-transparent";
  }
}

function RelatedLinks({ event }: { event: StreamEvent }) {
  const links: { href: string; label: string }[] = [];
  if (event.finding_id) {
    links.push({
      href: `/findings?id=${encodeURIComponent(event.finding_id)}`,
      label: "Finding",
    });
  }
  if (event.device_id) {
    links.push({
      href: `/devices?id=${encodeURIComponent(event.device_id)}`,
      label: "Device",
    });
  }
  if (event.person_id) {
    links.push({
      href: `/people?id=${encodeURIComponent(event.person_id)}`,
      label: "Person",
    });
  }
  if (links.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      {links.map((link) => (
        <Link
          key={link.href}
          href={link.href}
          className="font-medium text-foreground underline-offset-4 hover:underline"
        >
          {link.label}
        </Link>
      ))}
    </div>
  );
}

function LiveEventRow({ event }: { event: StreamEvent }) {
  return (
    <li
      className={cn(
        "border-l-4 px-3 py-3 sm:px-4",
        eventRowTone(event.severity),
      )}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={cn(severityTone(event.severity))}
            >
              {severityLabel(event.severity)}
            </Badge>
            <Badge variant="secondary">
              {streamEventKindLabel(event.kind)}
            </Badge>
            {event.source ? (
              <span className="text-xs text-muted-foreground">
                {sourceLabel(event.source)}
              </span>
            ) : null}
          </div>
          <p className="text-sm leading-snug">{event.summary}</p>
          <RelatedLinks event={event} />
        </div>
        <time
          className="shrink-0 text-xs text-muted-foreground tabular-nums"
          dateTime={event.occurred_at}
          title={new Date(event.occurred_at).toLocaleString()}
        >
          {formatRelativeTime(event.occurred_at)}
        </time>
      </div>
    </li>
  );
}

function LiveLoading() {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <div className="h-14 animate-pulse rounded-lg bg-muted" />
      <div className="h-20 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-20 animate-pulse rounded-lg bg-muted/60" />
      <div className="h-20 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading recent events…</p>
    </div>
  );
}

function LiveError({
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
        Couldn’t load live events
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

export function LiveFeed() {
  const {
    events,
    connectionStatus,
    error,
    isLoading,
    isError,
    isFetching,
    refetch,
  } = useLiveEvents();
  const connection = connectionCopy(connectionStatus);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Live</h1>
          <p className="text-sm text-muted-foreground">
            Meaningful household events as they happen — not every DNS lookup.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className={cn("gap-1.5", connection.tone)}
            aria-live="polite"
          >
            <Radio
              className={cn(
                "size-3",
                connectionStatus === "live" && "text-emerald-600",
                connectionStatus === "reconnecting" && "animate-pulse",
              )}
              aria-hidden
            />
            {connection.label}
          </Badge>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void refetch()}
            disabled={isFetching || isLoading}
          >
            <RefreshCw
              className={cn("size-3.5", isFetching && "animate-spin")}
            />
            {isFetching ? "Refreshing…" : "Refresh"}
          </Button>
        </div>
      </div>

      {isLoading ? <LiveLoading /> : null}

      {isError ? (
        <LiveError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {!isLoading && !isError ? (
        events.length === 0 ? (
          <p className="rounded-lg border border-dashed px-4 py-8 text-sm text-muted-foreground">
            No meaningful events yet. New findings and network changes will
            appear here.
          </p>
        ) : (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Showing {events.length}
              {events.length >= LIVE_EVENT_CAP
                ? ` (capped at ${LIVE_EVENT_CAP})`
                : null}{" "}
              · newest first
            </p>
            <ul className="divide-y overflow-hidden rounded-lg border">
              {events.map((event) => (
                <LiveEventRow key={event.id} event={event} />
              ))}
            </ul>
          </div>
        )
      ) : null}
    </div>
  );
}
