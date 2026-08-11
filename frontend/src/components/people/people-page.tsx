"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Plus, RefreshCw } from "lucide-react";
import { useState, type FormEvent } from "react";

import { PersonDetail } from "@/components/people/person-detail";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useCreatePerson, usePeople } from "@/hooks/use-people";
import type { PersonOut, PersonRole } from "@/lib/api/types";
import { personRoleLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

const PERSON_ROLES: PersonRole[] = ["parent", "child", "other"];

const fieldClassName =
  "flex h-8 w-full rounded-lg border border-input bg-background px-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

const textareaClassName =
  "min-h-20 w-full rounded-lg border border-input bg-background px-2.5 py-2 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

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
        No people yet. Use Add person to create a household member, then assign
        their devices.
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

function AddPersonSheet({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const router = useRouter();
  const create = useCreatePerson();
  const [name, setName] = useState("");
  const [role, setRole] = useState<PersonRole>("child");
  const [notes, setNotes] = useState("");

  function resetForm() {
    setName("");
    setRole("child");
    setNotes("");
    create.reset();
  }

  function handleOpenChange(next: boolean) {
    onOpenChange(next);
    if (!next) {
      resetForm();
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName) return;

    const trimmedNotes = notes.trim();
    create.mutate(
      {
        name: trimmedName,
        role,
        notes: trimmedNotes.length > 0 ? trimmedNotes : null,
      },
      {
        onSuccess: (person) => {
          handleOpenChange(false);
          router.push(`/people?id=${encodeURIComponent(person.id)}`);
        },
      },
    );
  }

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent side="right" className="w-full sm:max-w-md">
        <SheetHeader>
          <SheetTitle>Add person</SheetTitle>
          <SheetDescription>
            Create a household member so you can assign devices and attribute
            activity.
          </SheetDescription>
        </SheetHeader>
        <form
          onSubmit={onSubmit}
          className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-4 pb-4"
        >
          <div className="space-y-1.5">
            <label htmlFor="person-name" className="text-sm font-medium">
              Name
            </label>
            <input
              id="person-name"
              className={fieldClassName}
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Alex"
              autoComplete="off"
              required
              disabled={create.isPending}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="person-role" className="text-sm font-medium">
              Role
            </label>
            <select
              id="person-role"
              className={fieldClassName}
              value={role}
              onChange={(event) => setRole(event.target.value as PersonRole)}
              disabled={create.isPending}
            >
              {PERSON_ROLES.map((value) => (
                <option key={value} value={value}>
                  {personRoleLabel(value)}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1.5">
            <label htmlFor="person-notes" className="text-sm font-medium">
              Notes
            </label>
            <textarea
              id="person-notes"
              className={textareaClassName}
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="Optional notes"
              disabled={create.isPending}
            />
          </div>

          {create.isError ? (
            <p className="text-sm text-destructive" role="alert">
              {create.error instanceof Error
                ? create.error.message
                : "Couldn’t create person"}
            </p>
          ) : null}

          <div className="mt-auto flex flex-wrap gap-2 pt-2">
            <Button
              type="submit"
              size="sm"
              disabled={create.isPending || name.trim().length === 0}
            >
              {create.isPending ? "Adding…" : "Add person"}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={create.isPending}
              onClick={() => handleOpenChange(false)}
            >
              Cancel
            </Button>
          </div>
        </form>
      </SheetContent>
    </Sheet>
  );
}

function PeopleListView() {
  const { data, error, isLoading, isError, isFetching, refetch } = usePeople();
  const [addOpen, setAddOpen] = useState(false);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">People</h1>
          <p className="text-sm text-muted-foreground">
            Household members, their devices, and attributed activity.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            size="sm"
            onClick={() => setAddOpen(true)}
          >
            <Plus className="size-3.5" />
            Add person
          </Button>
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

      <AddPersonSheet open={addOpen} onOpenChange={setAddOpen} />
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
