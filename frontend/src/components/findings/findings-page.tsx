"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { FindingDetail } from "@/components/findings/finding-detail";
import { SuppressionsView } from "@/components/findings/suppressions-view";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { useDevices } from "@/hooks/use-devices";
import {
  type FindingListFilters,
  useFindings,
} from "@/hooks/use-findings";
import { usePeople } from "@/hooks/use-people";
import type {
  FindingOut,
  FindingSeverity,
  FindingStatus,
} from "@/lib/api/types";
import {
  deviceDisplayName,
  findingConfidenceLabel,
  findingStatusLabel,
  formatRelativeTime,
  severityLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

const selectClassName =
  "flex h-8 w-full min-w-0 rounded-lg border border-input bg-background px-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50 sm:w-auto sm:min-w-[10rem]";

const SEVERITIES: FindingSeverity[] = ["high", "medium", "low", "info"];
const STATUSES: FindingStatus[] = [
  "open",
  "acknowledged",
  "resolved",
  "dismissed",
];

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

function FindingsLoading() {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <div className="h-14 animate-pulse rounded-lg bg-muted" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading findings…</p>
    </div>
  );
}

function FindingsError({
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
        Couldn’t load findings
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

function FilterBar({
  filters,
  onChange,
}: {
  filters: FindingListFilters;
  onChange: (next: FindingListFilters) => void;
}) {
  const people = usePeople();
  const devices = useDevices();
  const personOptions = people.data?.people ?? [];
  const deviceOptions = devices.data?.devices ?? [];

  const hasFilters = Boolean(
    filters.severity || filters.person || filters.device || filters.status,
  );

  return (
    <div className="space-y-3">
      <div
        className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"
        role="group"
        aria-label="Finding filters"
      >
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Severity</span>
          <select
            className={selectClassName}
            value={filters.severity ?? ""}
            onChange={(event) =>
              onChange({
                ...filters,
                severity: (event.target.value || null) as FindingSeverity | null,
              })
            }
          >
            <option value="">All severities</option>
            {SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {severityLabel(severity)}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Status</span>
          <select
            className={selectClassName}
            value={filters.status ?? ""}
            onChange={(event) =>
              onChange({
                ...filters,
                status: (event.target.value || null) as FindingStatus | null,
              })
            }
          >
            <option value="">All statuses</option>
            {STATUSES.map((status) => (
              <option key={status} value={status}>
                {findingStatusLabel(status)}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Person</span>
          <select
            className={selectClassName}
            value={filters.person ?? ""}
            onChange={(event) =>
              onChange({
                ...filters,
                person: event.target.value || null,
              })
            }
            disabled={people.isLoading}
          >
            <option value="">All people</option>
            {personOptions.map((person) => (
              <option key={person.id} value={person.id}>
                {person.name}
              </option>
            ))}
          </select>
        </label>

        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Device</span>
          <select
            className={selectClassName}
            value={filters.device ?? ""}
            onChange={(event) =>
              onChange({
                ...filters,
                device: event.target.value || null,
              })
            }
            disabled={devices.isLoading}
          >
            <option value="">All devices</option>
            {deviceOptions.map((device) => (
              <option key={device.id} value={device.id}>
                {deviceDisplayName(device)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {hasFilters ? (
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() =>
            onChange({
              severity: null,
              person: null,
              device: null,
              status: null,
            })
          }
        >
          Clear filters
        </Button>
      ) : null}
    </div>
  );
}

function FindingList({ findings }: { findings: FindingOut[] }) {
  if (findings.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-sm text-muted-foreground">
        No findings match these filters.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {findings.map((finding) => {
        const subject =
          finding.subject_label?.trim() ||
          (!finding.person_id && !finding.device_id
            ? "unattributed"
            : "Attributed subject");

        return (
          <li key={finding.id}>
            <Link
              href={`/findings?id=${encodeURIComponent(finding.id)}`}
              className="flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-muted/40 sm:flex-row sm:items-start sm:justify-between sm:gap-4"
            >
              <div className="min-w-0 space-y-1.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge
                    variant="outline"
                    className={cn(severityTone(finding.severity))}
                  >
                    {severityLabel(finding.severity)}
                  </Badge>
                  <Badge variant="secondary">
                    {findingStatusLabel(finding.status)}
                  </Badge>
                  <Badge variant="outline">
                    {findingConfidenceLabel(finding.confidence)}
                  </Badge>
                </div>
                <p className="text-sm font-medium leading-snug">
                  {finding.title}
                </p>
                <p className="line-clamp-2 text-sm text-muted-foreground">
                  {finding.summary}
                </p>
                <p className="text-xs text-muted-foreground">
                  Involved: {subject}
                </p>
              </div>
              <time
                className="shrink-0 text-xs text-muted-foreground tabular-nums"
                dateTime={finding.occurred_at}
              >
                {formatRelativeTime(finding.occurred_at)}
              </time>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function FindingsListView() {
  const [filters, setFilters] = useState<FindingListFilters>({
    severity: null,
    person: null,
    device: null,
    status: "open",
  });
  const { data, error, isLoading, isError, isFetching, refetch } =
    useFindings(filters);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Findings</h1>
          <p className="text-sm text-muted-foreground">
            Explainable household signals. DNS lookups are not proof of content
            viewed.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href="/findings?view=suppressions"
            className={cn(buttonVariants({ variant: "outline", size: "sm" }))}
          >
            Suppressions
          </Link>
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

      <FilterBar filters={filters} onChange={setFilters} />

      {isLoading ? <FindingsLoading /> : null}

      {isError ? (
        <FindingsError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {data ? (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground tabular-nums">
            {data.count} finding{data.count === 1 ? "" : "s"}
          </p>
          <FindingList findings={data.items ?? []} />
        </div>
      ) : null}
    </div>
  );
}

export function FindingsPage() {
  const searchParams = useSearchParams();
  const findingId = searchParams.get("id");
  const view = searchParams.get("view");

  if (findingId) {
    return <FindingDetail findingId={findingId} />;
  }

  if (view === "suppressions") {
    return <SuppressionsView />;
  }

  return <FindingsListView />;
}
