"use client";

import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useSystemHealth } from "@/hooks/use-system-health";
import type {
  LastBatchOut,
  SourceErrorCountOut,
  SystemHealthOut,
} from "@/lib/api/types";
import { formatDateTime, formatRelativeTime, sourceLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

function tone(status: string): string {
  if (status === "ok") {
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300";
  }
  if (status === "degraded") {
    return "border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300";
  }
  return "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400";
}

function StatusPill({ status }: { status: string }) {
  return (
    <Badge variant="outline" className={cn(tone(status))}>
      {status}
    </Badge>
  );
}

function ComponentCard({
  title,
  status,
  detail,
  meta,
}: {
  title: string;
  status: string;
  detail?: string;
  meta?: ReactNode;
}) {
  return (
    <article className="space-y-2 rounded-lg border p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        <StatusPill status={status} />
      </div>
      {detail ? (
        <p className="text-sm text-muted-foreground">{detail}</p>
      ) : null}
      {meta}
    </article>
  );
}

function BatchRow({ batch }: { batch: LastBatchOut }) {
  return (
    <tr className="border-t align-top">
      <td className="py-2 pr-3 text-sm font-medium">
        {sourceLabel(batch.source)}
      </td>
      <td className="py-2 pr-3 text-sm">
        {batch.status ? (
          <Badge variant="outline">{batch.status}</Badge>
        ) : (
          "—"
        )}
      </td>
      <td className="py-2 pr-3 text-sm text-muted-foreground">
        {formatRelativeTime(batch.finished_at ?? batch.started_at)}
        <span className="mt-0.5 block text-xs">
          {formatDateTime(batch.finished_at ?? batch.started_at)}
        </span>
      </td>
      <td className="py-2 pr-3 text-sm tabular-nums">
        {batch.record_count ?? "—"}
      </td>
      <td className="max-w-[14rem] py-2 text-sm text-muted-foreground break-words">
        {batch.error || "—"}
      </td>
    </tr>
  );
}

function ErrorRow({ row }: { row: SourceErrorCountOut }) {
  return (
    <tr className="border-t">
      <td className="py-2 pr-3 text-sm font-medium">
        {sourceLabel(row.source)}
      </td>
      <td className="py-2 pr-3 text-sm tabular-nums">
        {row.failed_batches_24h}
      </td>
      <td className="py-2 text-sm">
        {row.source_status ? (
          <StatusPill status={row.source_status} />
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

function HealthBody({ data }: { data: SystemHealthOut }) {
  return (
    <div className="space-y-6">
      <div
        className={cn(
          "rounded-lg border px-4 py-4",
          tone(data.status).replace("text-", "text-"),
        )}
      >
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill status={data.status} />
          <p className="text-sm text-muted-foreground">
            Checked {formatRelativeTime(data.checked_at)} ·{" "}
            {formatDateTime(data.checked_at)}
          </p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <ComponentCard
          title="API"
          status={data.api.status}
          detail={data.api.detail}
        />
        <ComponentCard
          title="Database"
          status={data.database.status}
          detail={data.database.detail}
        />
        <ComponentCard
          title="Worker"
          status={data.worker.status}
          detail={data.worker.detail}
          meta={
            <dl className="grid gap-2 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Last heartbeat</dt>
                <dd>{formatRelativeTime(data.worker.last_seen_at)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Staleness</dt>
                <dd>
                  {data.worker.staleness_seconds == null
                    ? "—"
                    : `${data.worker.staleness_seconds}s`}
                </dd>
              </div>
            </dl>
          }
        />
      </div>

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">
            Last ingest batches
          </h2>
          <p className="text-sm text-muted-foreground">
            Most recent batch per source.
          </p>
        </div>
        <div className="overflow-x-auto rounded-lg border">
          <table className="min-w-full text-left">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Records</th>
                <th className="px-3 py-2 font-medium">Error</th>
              </tr>
            </thead>
            <tbody className="[&_td]:px-3">
              {data.last_batches.map((batch) => (
                <BatchRow key={batch.source} batch={batch} />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Separator />

      <section className="space-y-3">
        <div>
          <h2 className="text-base font-semibold tracking-tight">
            Error counts (24h)
          </h2>
          <p className="text-sm text-muted-foreground">
            Failed ingest batches in the last day, plus current source status.
          </p>
        </div>
        <div className="overflow-x-auto rounded-lg border">
          <table className="min-w-full text-left">
            <thead className="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">Failed batches</th>
                <th className="px-3 py-2 font-medium">Source status</th>
              </tr>
            </thead>
            <tbody className="[&_td]:px-3">
              {data.error_counts.map((row) => (
                <ErrorRow key={row.source} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export function SystemHealthPage() {
  const { data, error, isLoading, isFetching, isError, refetch } =
    useSystemHealth();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">
            System Health
          </h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Process and database reachability, worker liveness, last ingest
            batches, and recent error counts.
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
        <div className="space-y-3" aria-busy>
          <div className="h-16 animate-pulse rounded-lg bg-muted" />
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="h-28 animate-pulse rounded-lg bg-muted/70" />
            <div className="h-28 animate-pulse rounded-lg bg-muted/70" />
            <div className="h-28 animate-pulse rounded-lg bg-muted/70" />
          </div>
        </div>
      ) : null}

      {isError ? (
        <div
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-6"
          role="alert"
        >
          <p className="text-sm font-semibold text-destructive">
            Couldn’t load system health
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {error instanceof Error ? error.message : "Request failed"}
          </p>
        </div>
      ) : null}

      {data ? <HealthBody data={data} /> : null}
    </div>
  );
}
