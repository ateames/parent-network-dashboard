"use client";

import Link from "next/link";
import { ArrowLeft, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { useDeleteSuppression } from "@/hooks/use-delete-suppression";
import { useSuppressions } from "@/hooks/use-suppressions";
import type { SuppressionOut } from "@/lib/api/types";
import { formatRelativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

function SuppressionsLoading() {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <div className="h-14 animate-pulse rounded-lg bg-muted" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading suppressions…</p>
    </div>
  );
}

function SuppressionsError({
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
        Couldn’t load suppressions
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

function SuppressionRow({
  suppression,
}: {
  suppression: SuppressionOut;
}) {
  const remove = useDeleteSuppression();
  const [confirming, setConfirming] = useState(false);

  return (
    <li className="flex flex-col gap-3 px-4 py-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
      <div className="min-w-0 space-y-1.5">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="secondary">{suppression.rule_id}</Badge>
          <Badge variant="outline">{suppression.domain_pattern}</Badge>
        </div>
        <p className="truncate font-mono text-xs text-muted-foreground">
          {suppression.matching_key}
        </p>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span>By {suppression.created_by}</span>
          <span>{formatRelativeTime(suppression.created_at)}</span>
          {suppression.person_id ? (
            <Link
              href={`/people?id=${encodeURIComponent(suppression.person_id)}`}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              Person
            </Link>
          ) : null}
          {suppression.device_id ? (
            <Link
              href={`/devices?id=${encodeURIComponent(suppression.device_id)}`}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              Device
            </Link>
          ) : null}
          {!suppression.person_id && !suppression.device_id ? (
            <span>unattributed</span>
          ) : null}
          {suppression.source_finding_id ? (
            <Link
              href={`/findings?id=${encodeURIComponent(suppression.source_finding_id)}`}
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              Source finding
            </Link>
          ) : null}
        </div>
        {remove.isError ? (
          <p className="text-sm text-destructive" role="alert">
            {remove.error instanceof Error
              ? remove.error.message
              : "Couldn’t remove suppression"}
          </p>
        ) : null}
      </div>

      <div className="flex shrink-0 flex-wrap gap-2">
        {confirming ? (
          <>
            <Button
              type="button"
              size="sm"
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => remove.mutate(suppression.id)}
            >
              {remove.isPending ? "Removing…" : "Confirm remove"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={remove.isPending}
              onClick={() => setConfirming(false)}
            >
              Cancel
            </Button>
          </>
        ) : (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setConfirming(true)}
          >
            <Trash2 className="size-3.5" />
            Remove
          </Button>
        )}
      </div>
    </li>
  );
}

export function SuppressionsView() {
  const { data, error, isLoading, isError, isFetching, refetch } =
    useSuppressions();
  const items = data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-2">
          <Link
            href="/findings"
            className={cn(
              buttonVariants({ variant: "ghost", size: "sm" }),
              "-ml-2 w-fit",
            )}
          >
            <ArrowLeft className="size-3.5" />
            All findings
          </Link>
          <div className="space-y-1">
            <h1 className="text-2xl font-semibold tracking-tight">
              Suppressions
            </h1>
            <p className="text-sm text-muted-foreground">
              Active rules that skip equivalent findings. Removing one lets
              matching findings appear again.
            </p>
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

      {isLoading ? <SuppressionsLoading /> : null}

      {isError ? (
        <SuppressionsError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {data ? (
        items.length === 0 ? (
          <p className="rounded-lg border border-dashed px-4 py-8 text-sm text-muted-foreground">
            No active suppressions.
          </p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {items.map((suppression) => (
              <SuppressionRow
                key={suppression.id}
                suppression={suppression}
              />
            ))}
          </ul>
        )
      ) : null}
    </div>
  );
}
