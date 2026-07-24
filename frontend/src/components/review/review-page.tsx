"use client";

import Link from "next/link";
import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  type ResolveReviewVars,
  useResolveReview,
} from "@/hooks/use-resolve-review";
import { useReview } from "@/hooks/use-review";
import { ApiError } from "@/lib/api/client";
import type {
  CandidateDeviceOut,
  CorrelationStatus,
  ReviewItemOut,
} from "@/lib/api/types";
import {
  conflictReasonLabel,
  correlationStatusLabel,
  deviceDisplayName,
  evidenceKindLabel,
  formatConfidenceScore,
  formatDateTime,
  formatRelativeTime,
  identifierKindLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

type EvidenceMatch = {
  kind: string;
  device_id: string;
  weight: string;
  detail: Record<string, unknown>;
};

type ConflictItem = {
  reason: string;
  detail: Record<string, unknown>;
};

type TimeWindow = {
  start: string | null;
  end: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function parseMatches(evidence: ReviewItemOut["evidence"]): EvidenceMatch[] {
  const raw = evidence.matches;
  if (!Array.isArray(raw)) return [];

  const matches: EvidenceMatch[] = [];
  for (const entry of raw) {
    if (!isRecord(entry)) continue;
    const kind = asString(entry.kind);
    const deviceId = asString(entry.device_id);
    const weight =
      typeof entry.weight === "string" || typeof entry.weight === "number"
        ? String(entry.weight)
        : null;
    if (!kind || !deviceId || !weight) continue;

    const detail: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(entry)) {
      if (key === "kind" || key === "device_id" || key === "weight") continue;
      detail[key] = value;
    }
    matches.push({ kind, device_id: deviceId, weight, detail });
  }
  return matches;
}

function parseConflicts(
  conflicts: ReviewItemOut["conflicts"],
): ConflictItem[] {
  const raw = conflicts.items;
  if (!Array.isArray(raw)) return [];

  const items: ConflictItem[] = [];
  for (const entry of raw) {
    if (!isRecord(entry)) continue;
    const reason = asString(entry.reason);
    if (!reason) continue;
    const detail: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(entry)) {
      if (key === "reason") continue;
      detail[key] = value;
    }
    items.push({ reason, detail });
  }
  return items;
}

function parseWindow(evidence: ReviewItemOut["evidence"]): TimeWindow {
  const window = evidence.window;
  if (!isRecord(window)) {
    return { start: null, end: null };
  }
  return {
    start: asString(window.start),
    end: asString(window.end),
  };
}

function statusTone(status: CorrelationStatus): string {
  switch (status) {
    case "ambiguous":
      return "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-300";
    case "unattributed":
      return "border-border bg-muted/50 text-muted-foreground";
    case "attributed":
    default:
      return "border-border bg-background text-foreground";
  }
}

function deviceNameById(
  candidates: CandidateDeviceOut[],
  deviceId: string,
): string {
  const match = candidates.find((c) => c.id === deviceId);
  return match ? deviceDisplayName(match) : `Device ${deviceId.slice(0, 8)}`;
}

function ReviewLoading() {
  return (
    <div className="space-y-3" aria-busy="true" aria-live="polite">
      <div className="h-40 animate-pulse rounded-lg bg-muted" />
      <div className="h-40 animate-pulse rounded-lg bg-muted/70" />
      <p className="text-sm text-muted-foreground">Loading review queue…</p>
    </div>
  );
}

function ReviewError({
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
        Couldn’t load the review queue
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

function MatchDetail({ detail }: { detail: Record<string, unknown> }) {
  const parts: string[] = [];
  const ip = asString(detail.ip);
  const value = asString(detail.value);
  const assignmentId = asString(detail.assignment_id);
  const identifierId = asString(detail.identifier_id);

  if (ip) parts.push(`IP ${ip}`);
  if (value) parts.push(value);
  if (assignmentId) parts.push(`assignment ${assignmentId.slice(0, 8)}`);
  if (identifierId) parts.push(`identifier ${identifierId.slice(0, 8)}`);

  if (parts.length === 0) return null;
  return (
    <p className="mt-0.5 text-xs text-muted-foreground">{parts.join(" · ")}</p>
  );
}

function EvidenceSection({
  matches,
  candidates,
}: {
  matches: EvidenceMatch[];
  candidates: CandidateDeviceOut[];
}) {
  if (matches.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
        No matching evidence was found for this query.
      </p>
    );
  }

  return (
    <ul className="divide-y rounded-lg border">
      {matches.map((match, index) => (
        <li
          key={`${match.device_id}-${match.kind}-${index}`}
          className="px-3 py-2.5"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm font-medium">
                {evidenceKindLabel(match.kind)}
              </p>
              <p className="text-xs text-muted-foreground">
                Points to {deviceNameById(candidates, match.device_id)}
              </p>
              <MatchDetail detail={match.detail} />
            </div>
            <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
              weight {formatConfidenceScore(match.weight)}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}

function ConflictsSection({
  conflicts,
  candidates,
}: {
  conflicts: ConflictItem[];
  candidates: CandidateDeviceOut[];
}) {
  if (conflicts.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-3 py-4 text-sm text-muted-foreground">
        No conflicting signals recorded — confidence was not high enough to
        attribute automatically.
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {conflicts.map((conflict, index) => {
        const deviceIds = Array.isArray(conflict.detail.device_ids)
          ? conflict.detail.device_ids.filter(
              (id): id is string => typeof id === "string",
            )
          : [];
        const ip = asString(conflict.detail.ip);

        return (
          <li
            key={`${conflict.reason}-${index}`}
            className="rounded-lg border border-amber-500/35 bg-amber-500/8 px-3 py-3"
          >
            <p className="text-sm font-medium text-amber-950 dark:text-amber-200">
              {conflictReasonLabel(conflict.reason)}
            </p>
            {ip ? (
              <p className="mt-1 font-mono text-xs text-muted-foreground">
                {ip}
              </p>
            ) : null}
            {deviceIds.length > 0 ? (
              <ul className="mt-2 flex flex-wrap gap-1.5">
                {deviceIds.map((id) => (
                  <li key={id}>
                    <Badge variant="outline" className="font-normal">
                      {deviceNameById(candidates, id)}
                    </Badge>
                  </li>
                ))}
              </ul>
            ) : null}
            <p className="mt-2 text-xs text-muted-foreground">
              Conflicting evidence is kept as-is — the system will not guess.
            </p>
          </li>
        );
      })}
    </ul>
  );
}

function ResolvePanel({
  item,
  candidates,
  onResolve,
  busy,
}: {
  item: ReviewItemOut;
  candidates: CandidateDeviceOut[];
  onResolve: (vars: ResolveReviewVars) => Promise<void>;
  busy: boolean;
}) {
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [strengthen, setStrengthen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function submit(vars: ResolveReviewVars) {
    setErrorMessage(null);
    try {
      await onResolve(vars);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : error instanceof Error
            ? error.message
            : "Couldn’t save this decision";
      setErrorMessage(message);
    }
  }

  return (
    <div className="space-y-3 rounded-lg border bg-muted/20 px-3 py-3 sm:px-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold tracking-tight">Your decision</h3>
        <p className="text-xs text-muted-foreground">
          Only attribute when you are sure. Leaving this unattributed is the
          safer default — a wrong device is worse than no device.
        </p>
      </div>

      {candidates.length > 0 ? (
        <fieldset className="space-y-2" disabled={busy}>
          <legend className="text-xs font-medium text-muted-foreground">
            Candidate devices
          </legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {candidates.map((device) => {
              const selected = selectedDeviceId === device.id;
              return (
                <button
                  key={device.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() =>
                    setSelectedDeviceId((current) =>
                      current === device.id ? null : device.id,
                    )
                  }
                  className={cn(
                    "rounded-lg border px-3 py-2.5 text-left transition-colors",
                    selected
                      ? "border-foreground/40 bg-background"
                      : "border-border bg-background/60 hover:bg-muted/50",
                  )}
                >
                  <p className="text-sm font-medium">
                    {deviceDisplayName(device)}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    Optional — only if you recognize this device
                  </p>
                </button>
              );
            })}
          </div>
        </fieldset>
      ) : (
        <p className="rounded-lg border border-dashed px-3 py-3 text-sm text-muted-foreground">
          No candidate devices. You can leave this unattributed.
        </p>
      )}

      {selectedDeviceId ? (
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1 size-3.5 accent-foreground"
            checked={strengthen}
            disabled={busy}
            onChange={(event) => setStrengthen(event.target.checked)}
          />
          <span>
            <span className="font-medium">Strengthen future matching</span>
            <span className="mt-0.5 block text-xs text-muted-foreground">
              Confirm “{item.client_identifier}” as an identifier for this
              device. Historical raw data is never rewritten.
            </span>
          </span>
        </label>
      ) : null}

      <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        <Button
          type="button"
          variant="outline"
          className="justify-center sm:order-1"
          disabled={busy}
          onClick={() =>
            void submit({
              activityId: item.id,
              leaveUnattributed: true,
            })
          }
        >
          Leave unattributed
        </Button>
        <Button
          type="button"
          variant="secondary"
          className="justify-center sm:order-2"
          disabled={busy || !selectedDeviceId}
          onClick={() => {
            if (!selectedDeviceId) return;
            void submit({
              activityId: item.id,
              deviceId: selectedDeviceId,
              strengthenIdentifier: strengthen,
            });
          }}
        >
          {selectedDeviceId
            ? `Attribute to ${deviceNameById(candidates, selectedDeviceId)}`
            : "Attribute to a device"}
        </Button>
      </div>

      {errorMessage ? (
        <p className="text-sm text-destructive" role="alert">
          {errorMessage}
        </p>
      ) : null}
    </div>
  );
}

function ReviewItemCard({
  item,
  onResolve,
  busy,
}: {
  item: ReviewItemOut;
  onResolve: (vars: ResolveReviewVars) => Promise<void>;
  busy: boolean;
}) {
  const candidates = item.candidate_devices ?? [];
  const matches = parseMatches(item.evidence);
  const conflicts = parseConflicts(item.conflicts);
  const window = parseWindow(item.evidence);
  const hasConflicts = conflicts.length > 0;

  return (
    <article
      className={cn(
        "space-y-4 rounded-lg border px-4 py-4",
        hasConflicts && "border-amber-500/30",
      )}
    >
      <header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <Badge
              variant="outline"
              className={cn(statusTone(item.status))}
            >
              {correlationStatusLabel(item.status)}
            </Badge>
            <Badge variant="secondary">
              Confidence {formatConfidenceScore(item.confidence)}
            </Badge>
            {hasConflicts ? (
              <Badge
                variant="outline"
                className="border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-300"
              >
                Conflicting evidence
              </Badge>
            ) : null}
          </div>
          <h2 className="truncate font-mono text-sm font-semibold tracking-tight sm:text-base">
            {item.domain || "(empty domain)"}
          </h2>
          <p className="text-xs text-muted-foreground">
            DNS lookup only — not proof that someone viewed specific content.
          </p>
        </div>
        <time
          className="shrink-0 text-xs text-muted-foreground tabular-nums"
          dateTime={item.queried_at}
          title={formatDateTime(item.queried_at)}
        >
          {formatRelativeTime(item.queried_at)}
        </time>
      </header>

      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-muted-foreground">Client identifier</dt>
          <dd className="mt-0.5 font-mono text-sm">
            {item.client_identifier || "—"}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">
            {identifierKindLabel("ip")} at query time
          </dt>
          <dd className="mt-0.5 font-mono text-sm">
            {item.client_ip ?? "—"}
          </dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-xs text-muted-foreground">Correlation window</dt>
          <dd className="mt-0.5 text-sm tabular-nums">
            {window.start || window.end ? (
              <>
                {formatDateTime(window.start)}
                <span className="mx-1.5 text-muted-foreground">→</span>
                {formatDateTime(window.end)}
              </>
            ) : (
              <span className="text-muted-foreground">
                Queried {formatDateTime(item.queried_at)} (window not recorded)
              </span>
            )}
          </dd>
        </div>
      </dl>

      <Separator />

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-2">
          <h3 className="text-sm font-semibold tracking-tight">Evidence</h3>
          <EvidenceSection matches={matches} candidates={candidates} />
        </section>
        <section className="space-y-2">
          <h3 className="text-sm font-semibold tracking-tight">
            Conflicts & uncertainty
          </h3>
          <ConflictsSection conflicts={conflicts} candidates={candidates} />
        </section>
      </div>

      {candidates.length > 0 ? (
        <section className="space-y-2">
          <h3 className="text-sm font-semibold tracking-tight">
            Candidate devices
          </h3>
          <ul className="flex flex-wrap gap-2">
            {candidates.map((device) => (
              <li key={device.id}>
                <Link
                  href={`/devices?id=${encodeURIComponent(device.id)}`}
                  className={cn(
                    buttonVariants({ variant: "outline", size: "sm" }),
                  )}
                >
                  {deviceDisplayName(device)}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <ResolvePanel
        item={item}
        candidates={candidates}
        onResolve={onResolve}
        busy={busy}
      />

      <p className="text-[11px] text-muted-foreground">
        Logic {item.logic_version}
      </p>
    </article>
  );
}

export function ReviewPage() {
  const { data, error, isLoading, isError, isFetching, refetch } = useReview();
  const resolve = useResolveReview();
  const items = data?.items ?? [];

  async function handleResolve(vars: ResolveReviewVars) {
    await resolve.mutateAsync(vars);
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">Review</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Ambiguous and unattributed DNS correlations. Review the evidence,
            then attribute only when you are confident — or leave the activity
            unattributed.
          </p>
        </div>
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

      {isLoading ? <ReviewLoading /> : null}

      {isError ? (
        <ReviewError
          message={
            error instanceof Error ? error.message : "Unexpected error"
          }
          onRetry={() => void refetch()}
          isFetching={isFetching}
        />
      ) : null}

      {data ? (
        items.length === 0 ? (
          <p className="rounded-lg border border-dashed px-4 py-10 text-center text-sm text-muted-foreground">
            Review queue is empty. Nothing needs a decision right now.
          </p>
        ) : (
          <div className="space-y-3">
            <p className="text-xs text-muted-foreground tabular-nums">
              {items.length} item{items.length === 1 ? "" : "s"} needing review
            </p>
            <ul className="space-y-4">
              {items.map((item) => (
                <li key={item.id}>
                  <ReviewItemCard
                    item={item}
                    onResolve={handleResolve}
                    busy={
                      resolve.isPending &&
                      resolve.variables?.activityId === item.id
                    }
                  />
                </li>
              ))}
            </ul>
          </div>
        )
      ) : null}
    </div>
  );
}
