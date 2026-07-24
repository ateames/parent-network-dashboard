"use client";

import { RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { ActivitySubject } from "@/hooks/use-activity";
import { useActivity } from "@/hooks/use-activity";
import { useBaseline } from "@/hooks/use-baseline";
import type { ActivitySummaryOut, BaselineOut, DeviationOut } from "@/lib/api/types";
import {
  formatCompactNumber,
  formatMetricLabel,
  formatRelativeTime,
} from "@/lib/format";
import { cn } from "@/lib/utils";

const ACTIVITY_WINDOW = "24h";

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-3">
      <div className="min-w-0 space-y-0.5">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {description ? (
          <p className="text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children}
    </section>
  );
}

function PanelError({
  title,
  message,
  onRetry,
  isFetching,
}: {
  title: string;
  message: string;
  onRetry: () => void;
  isFetching: boolean;
}) {
  return (
    <div
      className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-4"
      role="alert"
    >
      <p className="text-sm font-semibold text-destructive">{title}</p>
      <p className="mt-1 text-sm text-muted-foreground">{message}</p>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="mt-3"
        onClick={onRetry}
        disabled={isFetching}
      >
        <RefreshCw className="size-3.5" />
        {isFetching ? "Retrying…" : "Try again"}
      </Button>
    </div>
  );
}

function MetricGrid({ activity }: { activity: ActivitySummaryOut }) {
  const metrics: { label: string; value: string }[] = [
    {
      label: "DNS lookups",
      value: formatCompactNumber(activity.dns_query_volume),
    },
    {
      label: "Blocked",
      value: `${formatCompactNumber(activity.blocked_query_count)} (${activity.blocked_query_pct.toFixed(1)}%)`,
    },
    {
      label: "Unique domains",
      value: formatCompactNumber(activity.unique_domain_count),
    },
    {
      label: "New domains",
      value: formatCompactNumber(activity.new_domain_count),
    },
    {
      label: "Active hours (UTC)",
      value: formatCompactNumber(activity.active_hour_count),
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
      {metrics.map((metric) => (
        <div key={metric.label} className="rounded-lg border px-3 py-3">
          <p className="text-xs font-medium text-muted-foreground">
            {metric.label}
          </p>
          <p className="mt-1 text-lg font-semibold tabular-nums tracking-tight">
            {metric.value}
          </p>
        </div>
      ))}
    </div>
  );
}

function DeviationsList({ deviations }: { deviations: DeviationOut[] }) {
  if (deviations.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No notable deviations from the stored baseline in this window.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {deviations.map((item) => (
        <li key={`${item.metric}-${item.reason}`} className="space-y-1 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">{formatMetricLabel(item.metric)}</Badge>
            {item.z_score != null ? (
              <span className="text-xs text-muted-foreground tabular-nums">
                z {item.z_score.toFixed(2)}
              </span>
            ) : null}
          </div>
          <p className="text-sm">{item.reason}</p>
        </li>
      ))}
    </ul>
  );
}

function BaselineMetrics({ baseline }: { baseline: BaselineOut }) {
  const entries = Object.values(baseline.metrics ?? {});
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No baseline metrics stored yet.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {entries.map((metric) => (
        <li
          key={metric.metric}
          className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium">
              {formatMetricLabel(metric.metric)}
            </p>
            <p className="text-xs text-muted-foreground">
              {metric.sample_count} sample
              {metric.sample_count === 1 ? "" : "s"}
            </p>
          </div>
          <p className="text-sm tabular-nums text-muted-foreground">
            mean {formatCompactNumber(metric.mean)} · p
            {Math.round(metric.percentile)}{" "}
            {formatCompactNumber(metric.percentile_value)}
          </p>
        </li>
      ))}
    </ul>
  );
}

function ActivityBody({
  subject,
}: {
  subject: ActivitySubject;
}) {
  const activity = useActivity(subject, ACTIVITY_WINDOW);
  const subjectId =
    subject.person !== undefined ? subject.person : subject.device ?? null;
  const baseline = useBaseline(subjectId, ACTIVITY_WINDOW);

  return (
    <div className="space-y-6">
      <Section
        title="Recent activity"
        description={`Attributed lookups over the last ${ACTIVITY_WINDOW}. DNS counts are not proof of content viewed.`}
      >
        {activity.isLoading ? (
          <div className="space-y-2" aria-busy="true">
            <div className="h-24 animate-pulse rounded-lg bg-muted/70" />
            <div className="h-16 animate-pulse rounded-lg bg-muted/50" />
          </div>
        ) : null}

        {activity.isError ? (
          <PanelError
            title="Couldn’t load activity"
            message={
              activity.error instanceof Error
                ? activity.error.message
                : "Unexpected error"
            }
            onRetry={() => void activity.refetch()}
            isFetching={activity.isFetching}
          />
        ) : null}

        {activity.data ? (
          <div className="space-y-3">
            <MetricGrid activity={activity.data} />
            {(activity.data.active_hours_utc ?? []).length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Active UTC hours:{" "}
                {activity.data.active_hours_utc
                  .slice()
                  .sort((a, b) => a - b)
                  .join(", ")}
              </p>
            ) : null}
            <DeviationsList deviations={activity.data.deviations ?? []} />
            <p className="text-xs text-muted-foreground">
              {activity.data.disclaimer} · logic {activity.data.logic_version}
            </p>
          </div>
        ) : null}
      </Section>

      <Section
        title="Baseline summary"
        description="Transparent stats over recent windows — mean, stddev, and percentile thresholds."
      >
        {baseline.isLoading ? (
          <div className="h-28 animate-pulse rounded-lg bg-muted/60" aria-busy="true" />
        ) : null}

        {baseline.isError ? (
          <PanelError
            title="Couldn’t load baseline"
            message={
              baseline.error instanceof Error
                ? baseline.error.message
                : "Unexpected error"
            }
            onRetry={() => void baseline.refetch()}
            isFetching={baseline.isFetching}
          />
        ) : null}

        {baseline.data ? (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>
                Computed {formatRelativeTime(baseline.data.computed_at)}
              </span>
              <span aria-hidden>·</span>
              <span>
                {baseline.data.sample_count} historical window
                {baseline.data.sample_count === 1 ? "" : "s"}
              </span>
            </div>
            <BaselineMetrics baseline={baseline.data} />
            {(baseline.data.typical_active_hours_utc ?? []).length > 0 ? (
              <p className="text-xs text-muted-foreground">
                Typical active UTC hours:{" "}
                {baseline.data.typical_active_hours_utc
                  .slice()
                  .sort((a, b) => a - b)
                  .join(", ")}
              </p>
            ) : null}
            <p className={cn("text-xs text-muted-foreground")}>
              {baseline.data.method}
            </p>
          </div>
        ) : null}
      </Section>
    </div>
  );
}

export function ActivitySummaryPanel({
  subject,
}: {
  subject: ActivitySubject | null;
}) {
  if (!subject) return null;
  return <ActivityBody subject={subject} />;
}
