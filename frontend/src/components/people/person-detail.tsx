"use client";

import Link from "next/link";
import { ArrowLeft, Plus, RefreshCw, Unlink } from "lucide-react";
import { useState } from "react";

import { ActivitySummaryPanel } from "@/components/activity/activity-summary-panel";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useDevices } from "@/hooks/use-devices";
import { usePerson } from "@/hooks/use-person";
import {
  useAssignDevice,
  useUnassignDevice,
} from "@/hooks/use-person-device-assignment";
import type { PersonOut } from "@/lib/api/types";
import {
  deviceDisplayName,
  formatRelativeTime,
  personRoleLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

function DetailLoading() {
  return (
    <div className="space-y-4" aria-busy="true" aria-live="polite">
      <div className="h-10 animate-pulse rounded-lg bg-muted" />
      <div className="h-28 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-40 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading person…</p>
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
        Couldn’t load this person
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

function AssignedDevices({
  person,
}: {
  person: PersonOut;
}) {
  const unassign = useUnassignDevice();
  const devices = person.devices ?? [];
  const pendingId =
    unassign.isPending && unassign.variables
      ? unassign.variables.deviceId
      : null;

  return (
    <div className="space-y-2">
      {devices.length === 0 ? (
        <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
          No devices assigned yet.
        </p>
      ) : (
        <ul className="divide-y rounded-lg border">
          {devices.map((device) => (
            <li
              key={device.id}
              className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0 space-y-0.5">
                <Link
                  href={`/devices?id=${encodeURIComponent(device.id)}`}
                  className="text-sm font-medium underline-offset-4 hover:underline"
                >
                  {deviceDisplayName(device)}
                </Link>
                <p className="text-xs text-muted-foreground">
                  Assigned {formatRelativeTime(device.assigned_at)}
                  {device.assigned_by ? ` · ${device.assigned_by}` : null}
                </p>
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={unassign.isPending && pendingId === device.id}
                onClick={() =>
                  unassign.mutate({ personId: person.id, deviceId: device.id })
                }
              >
                <Unlink className="size-3.5" />
                Unassign
              </Button>
            </li>
          ))}
        </ul>
      )}
      {unassign.isError ? (
        <p className="text-sm text-destructive" role="alert">
          {unassign.error instanceof Error
            ? unassign.error.message
            : "Unassign failed"}
        </p>
      ) : null}
    </div>
  );
}

function AssignDeviceSheet({
  person,
  open,
  onOpenChange,
}: {
  person: PersonOut;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const unassigned = useDevices({ unassigned: true });
  const assign = useAssignDevice();
  const assignedIds = new Set((person.devices ?? []).map((d) => d.id));
  const candidates = (unassigned.data?.devices ?? []).filter(
    (d) => !assignedIds.has(d.id),
  );

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Assign a device</SheetTitle>
          <SheetDescription>
            Pick an unassigned device for {person.name}. Reassigning moves it
            from anyone else.
          </SheetDescription>
        </SheetHeader>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 pb-4">
          {unassigned.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading devices…</p>
          ) : null}
          {unassigned.isError ? (
            <div className="space-y-3" role="alert">
              <p className="text-sm text-destructive">
                {unassigned.error instanceof Error
                  ? unassigned.error.message
                  : "Couldn’t load devices"}
              </p>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => void unassigned.refetch()}
              >
                Try again
              </Button>
            </div>
          ) : null}
          {!unassigned.isLoading && !unassigned.isError ? (
            candidates.length === 0 ? (
              <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
                No unassigned devices available.
              </p>
            ) : (
              <ul className="divide-y rounded-lg border">
                {candidates.map((device) => {
                  const pending =
                    assign.isPending &&
                    assign.variables?.deviceId === device.id;
                  return (
                    <li
                      key={device.id}
                      className="flex items-center justify-between gap-3 px-3 py-2.5"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-medium">
                          {deviceDisplayName(device)}
                        </p>
                        <p className="truncate text-xs text-muted-foreground">
                          {device.current_ip ?? "No current IP"}
                          {device.is_unknown ? " · unknown" : null}
                        </p>
                      </div>
                      <Button
                        type="button"
                        size="sm"
                        disabled={assign.isPending}
                        onClick={() => {
                          assign.mutate(
                            {
                              personId: person.id,
                              deviceId: device.id,
                              device: {
                                id: device.id,
                                display_name: device.display_name,
                              },
                            },
                            {
                              onSuccess: () => onOpenChange(false),
                            },
                          );
                        }}
                      >
                        {pending ? "Assigning…" : "Assign"}
                      </Button>
                    </li>
                  );
                })}
              </ul>
            )
          ) : null}
          {assign.isError ? (
            <p className="mt-3 text-sm text-destructive" role="alert">
              {assign.error instanceof Error
                ? assign.error.message
                : "Assign failed"}
            </p>
          ) : null}
        </div>
      </SheetContent>
    </Sheet>
  );
}

export function PersonDetail({ personId }: { personId: string }) {
  const { data, error, isLoading, isError, isFetching, refetch } =
    usePerson(personId);
  const [assignOpen, setAssignOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <Link
            href="/people"
            className={cn(
              buttonVariants({ variant: "ghost", size: "sm" }),
              "-ml-2 w-fit",
            )}
          >
            <ArrowLeft className="size-3.5" />
            All people
          </Link>
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              {data?.name ?? "Person"}
            </h1>
            {data ? (
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">{personRoleLabel(data.role)}</Badge>
                <span className="text-xs text-muted-foreground">
                  {(data.devices ?? []).length} device
                  {(data.devices ?? []).length === 1 ? "" : "s"}
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
          {data.notes ? (
            <p className="rounded-lg border px-4 py-3 text-sm text-muted-foreground">
              {data.notes}
            </p>
          ) : null}

          <section className="space-y-3">
            <div className="flex flex-wrap items-end justify-between gap-2">
              <div className="space-y-0.5">
                <h2 className="text-base font-semibold tracking-tight">
                  Assigned devices
                </h2>
                <p className="text-sm text-muted-foreground">
                  Durable device identity linked to this person.
                </p>
              </div>
              <Button
                type="button"
                size="sm"
                onClick={() => setAssignOpen(true)}
              >
                <Plus className="size-3.5" />
                Assign device
              </Button>
            </div>
            <AssignedDevices person={data} />
          </section>

          <Separator />

          <ActivitySummaryPanel subject={{ person: data.id }} />

          <p className="text-xs text-muted-foreground">
            Person logic {data.logic_version}
          </p>

          <AssignDeviceSheet
            person={data}
            open={assignOpen}
            onOpenChange={setAssignOpen}
          />
        </>
      ) : null}
    </div>
  );
}
