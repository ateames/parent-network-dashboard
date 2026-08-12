"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { DeviceDetail } from "@/components/devices/device-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  type DeviceListFilters,
  useDevices,
} from "@/hooks/use-devices";
import type { DeviceSummaryOut } from "@/lib/api/types";
import {
  deviceDisplayName,
  formatRelativeTime,
  personRoleLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

type FilterKey = keyof DeviceListFilters;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "online", label: "Online" },
  { key: "unknown", label: "Unknown" },
  { key: "unassigned", label: "Unassigned" },
];

function DevicesLoading() {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <div className="h-14 animate-pulse rounded-lg bg-muted" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading devices…</p>
    </div>
  );
}

function DevicesError({
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
        Couldn’t load devices
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
  onToggle,
}: {
  filters: DeviceListFilters;
  onToggle: (key: FilterKey) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Device filters">
      {FILTERS.map((filter) => {
        const active = filters[filter.key] === true;
        return (
          <Button
            key={filter.key}
            type="button"
            size="sm"
            variant={active ? "default" : "outline"}
            aria-pressed={active}
            onClick={() => onToggle(filter.key)}
          >
            {filter.label}
          </Button>
        );
      })}
    </div>
  );
}

function DeviceList({ devices }: { devices: DeviceSummaryOut[] }) {
  if (devices.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-sm text-muted-foreground">
        No devices match these filters.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {devices.map((device) => (
        <li key={device.id}>
          <Link
            href={`/devices?id=${encodeURIComponent(device.id)}`}
            className="flex flex-col gap-2 px-4 py-3 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
          >
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <p className="text-sm font-medium">
                  {deviceDisplayName(device)}
                </p>
                {device.is_unknown ? (
                  <Badge
                    variant="outline"
                    className="border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300"
                  >
                    Unknown
                  </Badge>
                ) : null}
                {device.internet_restriction?.status === "active" ? (
                  <Badge
                    variant="outline"
                    className="border-destructive/40 bg-destructive/10 text-destructive"
                  >
                    Internet disabled
                  </Badge>
                ) : null}
                {!device.assigned_person ? (
                  <Badge variant="outline">Unassigned</Badge>
                ) : null}
              </div>
              <p className="truncate text-sm text-muted-foreground">
                {device.current_ip ?? "No current IP"}
                {device.assigned_person
                  ? ` · ${device.assigned_person.name} (${personRoleLabel(device.assigned_person.role)})`
                  : null}
              </p>
            </div>
            <p className="shrink-0 text-xs text-muted-foreground tabular-nums">
              {formatRelativeTime(device.last_seen)}
            </p>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function DevicesListView() {
  const [filters, setFilters] = useState<DeviceListFilters>({});
  const { data, error, isLoading, isError, isFetching, refetch } =
    useDevices(filters);

  function toggleFilter(key: FilterKey) {
    setFilters((prev) => {
      const next = { ...prev };
      if (next[key] === true) {
        delete next[key];
      } else {
        next[key] = true;
      }
      return next;
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Devices</h1>
          <p className="text-sm text-muted-foreground">
            Durable device inventory — MAC / UniFi id / hostname, not IP alone.
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

      <FilterBar filters={filters} onToggle={toggleFilter} />

      {isLoading ? <DevicesLoading /> : null}

      {isError ? (
        <DevicesError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {data ? (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">
            {data.devices.length} device
            {data.devices.length === 1 ? "" : "s"}
          </p>
          <DeviceList devices={data.devices} />
        </div>
      ) : null}
    </div>
  );
}

export function DevicesPage() {
  const searchParams = useSearchParams();
  const deviceId = searchParams.get("id");

  if (deviceId) {
    return <DeviceDetail deviceId={deviceId} />;
  }

  return <DevicesListView />;
}
