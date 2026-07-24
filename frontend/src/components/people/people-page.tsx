"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { RefreshCw } from "lucide-react";

import { PersonDetail } from "@/components/people/person-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { usePeople } from "@/hooks/use-people";
import type { PersonOut } from "@/lib/api/types";
import { personRoleLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

function PeopleLoading() {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <div className="h-14 animate-pulse rounded-lg bg-muted" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-14 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading people…</p>
    </div>
  );
}

function PeopleError({
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
        Couldn’t load people
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

function PeopleList({ people }: { people: PersonOut[] }) {
  if (people.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-8 text-sm text-muted-foreground">
        No people yet. Household members will show up here once they’re added.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {people.map((person) => {
        const deviceCount = person.devices?.length ?? 0;
        return (
          <li key={person.id}>
            <Link
              href={`/people?id=${encodeURIComponent(person.id)}`}
              className="flex flex-col gap-1 px-4 py-3 transition-colors hover:bg-muted/40 sm:flex-row sm:items-center sm:justify-between sm:gap-4"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="text-sm font-medium">{person.name}</p>
                  <Badge variant="secondary">
                    {personRoleLabel(person.role)}
                  </Badge>
                </div>
                {person.notes ? (
                  <p className="line-clamp-1 text-sm text-muted-foreground">
                    {person.notes}
                  </p>
                ) : null}
              </div>
              <p className="shrink-0 text-xs text-muted-foreground tabular-nums">
                {deviceCount} device{deviceCount === 1 ? "" : "s"}
              </p>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function PeopleListView() {
  const { data, error, isLoading, isError, isFetching, refetch } = usePeople();

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">People</h1>
          <p className="text-sm text-muted-foreground">
            Household members, their devices, and attributed activity.
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

      {isLoading ? <PeopleLoading /> : null}

      {isError ? (
        <PeopleError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {data ? <PeopleList people={data.people ?? []} /> : null}
    </div>
  );
}

export function PeoplePage() {
  const searchParams = useSearchParams();
  const personId = searchParams.get("id");

  if (personId) {
    return <PersonDetail personId={personId} />;
  }

  return <PeopleListView />;
}
