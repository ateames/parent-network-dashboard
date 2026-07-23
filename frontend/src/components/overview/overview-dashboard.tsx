"use client";

import Link from "next/link";
import {
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  ShieldAlert,
} from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useDashboardSummary } from "@/hooks/use-dashboard-summary";
import type {
  ActiveChild,
  AttentionItem,
  DashboardDevice,
  DashboardSummary,
  DataHealthSource,
  FindingsBySeverity,
  RecentActivityItem,
} from "@/lib/api/types";
import {
  activityKindLabel,
  attentionKindLabel,
  deviceDisplayName,
  formatRelativeTime,
  sourceLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

function Section({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0 space-y-0.5">
          <h2 className="text-base font-semibold tracking-tight">{title}</h2>
          {description ? (
            <p className="text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function IncompleteBadge({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <Badge
      variant="outline"
      className="border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300"
    >
      Data incomplete
    </Badge>
  );
}

function StatusBanner({ summary }: { summary: DashboardSummary }) {
  const needsAttention = summary.status === "attention-needed";

  return (
    <div
      className={cn(
        "rounded-lg border px-4 py-4 sm:px-5",
        needsAttention
          ? "border-amber-500/40 bg-amber-500/10"
          : "border-emerald-500/35 bg-emerald-500/10",
      )}
      role="status"
    >
      <div className="flex items-start gap-3">
        {needsAttention ? (
          <AlertTriangle
            className="mt-0.5 size-5 shrink-0 text-amber-700 dark:text-amber-300"
            aria-hidden
          />
        ) : (
          <CheckCircle2
            className="mt-0.5 size-5 shrink-0 text-emerald-700 dark:text-emerald-400"
            aria-hidden
          />
        )}
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-semibold tracking-tight">
            {needsAttention
              ? "Household needs attention"
              : "Household looks settled"}
          </p>
          <p className="text-sm text-foreground/80">{summary.status_reason}</p>
        </div>
      </div>
    </div>
  );
}

function DataIncompleteBanner({ summary }: { summary: DashboardSummary }) {
  if (!summary.data_incomplete) return null;

  const sources = summary.incomplete_sources ?? [];

  return (
    <div
      className="rounded-lg border border-amber-500/40 bg-amber-500/5 px-4 py-3 sm:px-5"
      role="status"
    >
      <div className="flex items-start gap-3">
        <ShieldAlert
          className="mt-0.5 size-5 shrink-0 text-amber-700 dark:text-amber-300"
          aria-hidden
        />
        <div className="min-w-0 space-y-1">
          <p className="text-sm font-semibold tracking-tight">
            Some data is incomplete
          </p>
          <p className="text-sm text-muted-foreground">
            {sources.length > 0
              ? `Missing or stale from: ${sources.map(sourceLabel).join(", ")}. Counts that depend on those sources may be blank rather than zero.`
              : "One or more ingest sources are missing or stale. Counts that depend on them may be blank rather than zero."}
          </p>
        </div>
      </div>
    </div>
  );
}

function AttentionList({ items }: { items: AttentionItem[] }) {
  if (items.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
        Nothing needs your attention right now.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {items.map((item, index) => (
        <li
          key={`${item.kind}-${item.id ?? index}`}
          className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
        >
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{attentionKindLabel(item.kind)}</Badge>
              {item.source ? (
                <span className="text-xs text-muted-foreground">
                  {sourceLabel(item.source)}
                </span>
              ) : null}
            </div>
            <p className="text-sm">{item.summary}</p>
          </div>
        </li>
      ))}
    </ul>
  );
}

function SnapshotCard({
  title,
  value,
  incomplete,
  emptyHint,
  children,
}: {
  title: string;
  value: string;
  incomplete?: boolean;
  emptyHint?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-36 flex-col rounded-lg border p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-muted-foreground">{title}</p>
        <IncompleteBadge show={Boolean(incomplete)} />
      </div>
      <p className="mt-2 text-3xl font-semibold tracking-tight tabular-nums">
        {value}
      </p>
      <div className="mt-3 min-h-0 flex-1">
        {children ?? (
          <p className="text-sm text-muted-foreground">{emptyHint}</p>
        )}
      </div>
    </div>
  );
}

function DeviceChips({ devices }: { devices: DashboardDevice[] }) {
  if (devices.length === 0) return null;
  const shown = devices.slice(0, 4);
  const rest = devices.length - shown.length;

  return (
    <ul className="space-y-1.5">
      {shown.map((device) => (
        <li key={device.id} className="truncate text-sm">
          {deviceDisplayName(device)}
          {device.assigned_person_name ? (
            <span className="text-muted-foreground">
              {" "}
              · {device.assigned_person_name}
            </span>
          ) : null}
        </li>
      ))}
      {rest > 0 ? (
        <li className="text-xs text-muted-foreground">+{rest} more</li>
      ) : null}
    </ul>
  );
}

function ActiveChildrenList({ people }: { people: ActiveChild[] }) {
  if (people.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No children active recently.</p>
    );
  }

  return (
    <ul className="space-y-1.5">
      {people.slice(0, 4).map((child) => (
        <li key={child.person_id} className="truncate text-sm">
          {child.name}
          <span className="text-muted-foreground">
            {" "}
            · {formatRelativeTime(child.last_activity_at)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SnapshotGrid({ summary }: { summary: DashboardSummary }) {
  const activeChildren = summary.active_children ?? [];
  const online = summary.online_devices;
  const unknown = summary.unknown_unassigned;

  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      <SnapshotCard
        title="Children active now"
        value={
          summary.active_children_incomplete
            ? "—"
            : String(activeChildren.length)
        }
        incomplete={summary.active_children_incomplete}
        emptyHint="No recent child activity."
      >
        {!summary.active_children_incomplete ? (
          <ActiveChildrenList people={activeChildren} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Waiting on complete source data.
          </p>
        )}
      </SnapshotCard>

      <SnapshotCard
        title="Devices online"
        value={online.incomplete || online.count == null ? "—" : String(online.count)}
        incomplete={online.incomplete}
        emptyHint="No devices currently online."
      >
        {!online.incomplete ? (
          <DeviceChips devices={online.devices ?? []} />
        ) : (
          <p className="text-sm text-muted-foreground">
            UniFi data is incomplete, so online counts are hidden.
          </p>
        )}
      </SnapshotCard>

      <SnapshotCard
        title="Unknown / unassigned"
        value={
          unknown.incomplete || unknown.count == null
            ? "—"
            : String(unknown.count)
        }
        incomplete={unknown.incomplete}
        emptyHint="Every known device has an assignment."
      >
        {!unknown.incomplete ? (
          (unknown.devices ?? []).length > 0 ? (
            <DeviceChips devices={unknown.devices ?? []} />
          ) : (
            <p className="text-sm text-muted-foreground">
              Every known device has an assignment.
            </p>
          )
        ) : (
          <p className="text-sm text-muted-foreground">
            Device roster depends on incomplete UniFi data.
          </p>
        )}
      </SnapshotCard>
    </div>
  );
}

function RecentActivity({
  incomplete,
  items,
}: {
  incomplete: boolean;
  items: RecentActivityItem[];
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <IncompleteBadge show={incomplete} />
      </div>
      {incomplete ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
          Recent activity is incomplete while DNS or correlation data is
          missing.
        </p>
      ) : items.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
          No meaningful recent activity to show.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {items.slice(0, 8).map((item, index) => (
            <li
              key={`${item.kind}-${item.at}-${index}`}
              className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="secondary">
                    {activityKindLabel(item.kind)}
                  </Badge>
                  {item.person_name ? (
                    <span className="text-xs text-muted-foreground">
                      {item.person_name}
                    </span>
                  ) : null}
                </div>
                <p className="text-sm">{item.summary}</p>
                {item.domain ? (
                  <p className="truncate font-mono text-xs text-muted-foreground">
                    {item.domain}
                  </p>
                ) : null}
              </div>
              <time
                className="shrink-0 text-xs text-muted-foreground tabular-nums"
                dateTime={item.at}
              >
                {formatRelativeTime(item.at)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FindingsStrip({ findings }: { findings: FindingsBySeverity }) {
  const rows: { key: keyof FindingsBySeverity; label: string; tone: string }[] =
    [
      {
        key: "high",
        label: "High",
        tone: "border-red-500/30 bg-red-500/10 text-red-800 dark:text-red-300",
      },
      {
        key: "medium",
        label: "Medium",
        tone: "border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-300",
      },
      {
        key: "low",
        label: "Low",
        tone: "border-border bg-muted/40 text-foreground",
      },
      {
        key: "info",
        label: "Info",
        tone: "border-border bg-background text-muted-foreground",
      },
    ];

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {rows.map((row) => (
        <div
          key={row.key}
          className={cn(
            "rounded-lg border px-3 py-3 text-center",
            row.tone,
          )}
        >
          <p className="text-2xl font-semibold tabular-nums">
            {findings[row.key] ?? 0}
          </p>
          <p className="mt-0.5 text-xs font-medium uppercase tracking-wide">
            {row.label}
          </p>
        </div>
      ))}
    </div>
  );
}

function DataHealthStrip({
  sources,
  incompleteSources,
}: {
  sources: DataHealthSource[];
  incompleteSources: string[];
}) {
  const incomplete = new Set(incompleteSources);
  const ordered = ["pihole_api", "unifi_api", "unifi_syslog"] as const;

  const bySource = new Map(sources.map((s) => [s.source, s]));

  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {ordered.map((key) => {
        const source = bySource.get(key);
        const status = source?.status ?? "down";
        const marksIncomplete = incomplete.has(key);

        return (
          <div
            key={key}
            className={cn(
              "rounded-lg border px-3 py-3",
              status === "ok" &&
                !marksIncomplete &&
                "border-emerald-500/30 bg-emerald-500/5",
              (status === "degraded" || marksIncomplete) &&
                status !== "down" &&
                "border-amber-500/40 bg-amber-500/10",
              status === "down" && "border-red-500/40 bg-red-500/10",
            )}
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-medium">{sourceLabel(key)}</p>
              <div className="flex flex-wrap items-center gap-1.5">
                {marksIncomplete ? (
                  <Badge
                    variant="outline"
                    className="border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300"
                  >
                    Incomplete
                  </Badge>
                ) : null}
                <Badge
                  variant="outline"
                  className={cn(
                    status === "ok" &&
                      "border-emerald-500/40 text-emerald-800 dark:text-emerald-300",
                    status === "degraded" &&
                      "border-amber-500/40 text-amber-800 dark:text-amber-300",
                    status === "down" &&
                      "border-red-500/40 text-red-800 dark:text-red-300",
                  )}
                >
                  {status}
                </Badge>
              </div>
            </div>
            <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
              {source?.detail ?? "No health report yet"}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function OverviewLoading() {
  return (
    <div className="space-y-6" aria-busy="true" aria-live="polite">
      <div className="h-20 animate-pulse rounded-lg bg-muted" />
      <div className="h-16 animate-pulse rounded-lg bg-muted/70" />
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <div className="h-36 animate-pulse rounded-lg bg-muted/60" />
        <div className="h-36 animate-pulse rounded-lg bg-muted/60" />
        <div className="h-36 animate-pulse rounded-lg bg-muted/60" />
      </div>
      <div className="h-48 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading household summary…</p>
    </div>
  );
}

function OverviewError({
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
        Couldn’t load the household overview
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

export function OverviewDashboard() {
  const { data, error, isLoading, isError, isFetching, refetch } =
    useDashboardSummary();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
          <p className="text-sm text-muted-foreground">
            A quick read on how the household network looks right now.
          </p>
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

      {isLoading ? <OverviewLoading /> : null}

      {isError ? (
        <OverviewError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {data ? (
        <>
          <StatusBanner summary={data} />
          <DataIncompleteBanner summary={data} />

          <Section
            title="Needs attention"
            description={
              data.attention.count > 0
                ? `${data.attention.count} item${data.attention.count === 1 ? "" : "s"} to look at`
                : "Clear for now"
            }
            action={
              <Link
                href="/review"
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
              >
                Open review
              </Link>
            }
          >
            <AttentionList items={data.attention.items ?? []} />
          </Section>

          <Separator />

          <Section
            title="Right now"
            description="Who’s active, what’s online, and what still needs a person."
          >
            <SnapshotGrid summary={data} />
          </Section>

          <Separator />

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
            <Section
              title="Recent meaningful activity"
              description="Blocked lookups, review items, and attributed DNS — not every request."
            >
              <RecentActivity
                incomplete={data.recent_activity.incomplete}
                items={data.recent_activity.items ?? []}
              />
            </Section>

            <Section
              title="Open findings"
              description="By severity. DNS counts are lookups, not proof of content viewed."
              action={
                <Link
                  href="/findings"
                  className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
                >
                  All findings
                </Link>
              }
            >
              <FindingsStrip
                findings={
                  data.findings_by_severity ?? {
                    critical: 0,
                    high: 0,
                    medium: 0,
                    low: 0,
                    info: 0,
                  }
                }
              />
            </Section>
          </div>

          <Separator />

          <Section
            title="Data health"
            description="Pi-hole, UniFi, and syslog must be healthy for a complete picture."
            action={
              <Link
                href="/health"
                className={cn(buttonVariants({ variant: "ghost", size: "sm" }))}
              >
                Health details
              </Link>
            }
          >
            <DataHealthStrip
              sources={data.data_health.sources ?? []}
              incompleteSources={data.incomplete_sources ?? []}
            />
          </Section>

          <p className="text-xs text-muted-foreground">
            Updated {formatRelativeTime(data.generated_at)} · logic{" "}
            {data.logic_version}
          </p>
        </>
      ) : null}
    </div>
  );
}
