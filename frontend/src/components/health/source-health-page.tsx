"use client";

import { RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useSourceHealth } from "@/hooks/use-source-health";
import type { SourceHealthOut, SourceHealthStatus } from "@/lib/api/types";
import { formatDateTime, formatRelativeTime, sourceLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

function statusTone(status: SourceHealthStatus): string {
  if (status === "ok") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300";
  }
  if (status === "degraded") {
    return "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300";
  }
  return "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400";
}

function SourceCard({ source }: { source: SourceHealthOut }) {
  return (
    <article className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h2 className="text-base font-semibold tracking-tight">
            {sourceLabel(source.source)}
          </h2>
          <p className="font-mono text-xs text-muted-foreground">
            {source.source}
          </p>
        </div>
        <Badge variant="outline" className={cn(statusTone(source.status))}>
          {source.status}
        </Badge>
      </div>

      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div className="space-y-0.5">
          <dt className="text-muted-foreground">Last success</dt>
          <dd>
            {formatRelativeTime(source.last_success_at)}
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {formatDateTime(source.last_success_at)}
            </span>
          </dd>
        </div>
        <div className="space-y-0.5">
          <dt className="text-muted-foreground">Last attempt</dt>
          <dd>
            {formatRelativeTime(source.last_attempt_at)}
            <span className="mt-0.5 block text-xs text-muted-foreground">
              {formatDateTime(source.last_attempt_at)}
            </span>
          </dd>
        </div>
        <div className="space-y-0.5">
          <dt className="text-muted-foreground">Staleness</dt>
          <dd>
            {source.staleness_seconds == null
              ? "—"
              : `${source.staleness_seconds.toLocaleString()}s`}
          </dd>
        </div>
        <div className="space-y-0.5 sm:col-span-2">
          <dt className="text-muted-foreground">Detail</dt>
          <dd className="break-words">{source.detail || "—"}</dd>
        </div>
      </dl>
    </article>
  );
}

export function SourceHealthPage() {
  const { data, error, isLoading, isFetching, isError, refetch } =
    useSourceHealth();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            Source Health
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Per-source ingest status from Pi-hole, UniFi API, and UniFi syslog.
            Status is derived from last success, consecutive failures, and
            staleness windows.
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          disabled={isFetching}
        >
          <RefreshCw className={cn("size-3.5", isFetching && "animate-spin")} />
          {isFetching ? "Refreshing…" : "Refresh"}
        </Button>
      </div>

      {isLoading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-busy>
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="h-44 animate-pulse rounded-lg bg-muted"
            />
          ))}
        </div>
      ) : null}

      {isError ? (
        <div
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-6"
          role="alert"
        >
          <p className="text-sm font-semibold text-destructive">
            Couldn’t load source health
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {error instanceof Error ? error.message : "Request failed"}
          </p>
        </div>
      ) : null}

      {data ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {data.sources.map((source) => (
            <SourceCard key={source.source} source={source} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
