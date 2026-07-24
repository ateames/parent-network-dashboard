"use client";

import Link from "next/link";
import { ArrowLeft, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useFinding } from "@/hooks/use-finding";
import { useFindingFeedback } from "@/hooks/use-finding-feedback";
import type {
  FindingFeedbackClassification,
  FindingOut,
  FindingSeverity,
} from "@/lib/api/types";
import {
  feedbackClassificationLabel,
  findingConfidenceLabel,
  findingStatusLabel,
  formatRelativeTime,
  severityLabel,
} from "@/lib/format";
import { cn } from "@/lib/utils";

const FEEDBACK_ACTIONS: {
  classification: FindingFeedbackClassification;
  variant: "default" | "outline" | "secondary" | "destructive";
  description: string;
}[] = [
  {
    classification: "expected",
    variant: "outline",
    description: "Normal for this household — dismiss",
  },
  {
    classification: "concerning",
    variant: "destructive",
    description: "Worth attention — keep acknowledged",
  },
  {
    classification: "incorrect",
    variant: "outline",
    description: "Rule misfired — dismiss",
  },
  {
    classification: "ignore_once",
    variant: "outline",
    description: "Dismiss this instance only",
  },
  {
    classification: "suppress_similar",
    variant: "secondary",
    description: "Skip equivalent findings going forward",
  },
  {
    classification: "needs_investigation",
    variant: "default",
    description: "Flag for follow-up",
  },
  {
    classification: "acknowledge",
    variant: "outline",
    description: "Seen — leave open for later",
  },
  {
    classification: "resolve",
    variant: "default",
    description: "Handled — mark resolved",
  },
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

function DetailLoading() {
  return (
    <div className="space-y-4" aria-busy="true" aria-live="polite">
      <div className="h-10 animate-pulse rounded-lg bg-muted" />
      <div className="h-36 animate-pulse rounded-lg bg-muted/70" />
      <div className="h-40 animate-pulse rounded-lg bg-muted/50" />
      <p className="text-sm text-muted-foreground">Loading finding…</p>
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
        Couldn’t load this finding
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

function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="space-y-2">
      <h2 className="text-base font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

function InvolvedSubject({ finding }: { finding: FindingOut }) {
  const label =
    finding.subject_label?.trim() ||
    (finding.person_id || finding.device_id ? "Attributed subject" : "unattributed");

  return (
    <div className="space-y-2 rounded-lg border px-4 py-3">
      <p className="text-sm font-medium">{label}</p>
      <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {finding.person_id ? (
          <Link
            href={`/people?id=${encodeURIComponent(finding.person_id)}`}
            className="font-medium text-foreground underline-offset-4 hover:underline"
          >
            Person
          </Link>
        ) : null}
        {finding.device_id ? (
          <Link
            href={`/devices?id=${encodeURIComponent(finding.device_id)}`}
            className="font-medium text-foreground underline-offset-4 hover:underline"
          >
            Device
          </Link>
        ) : null}
        {!finding.person_id && !finding.device_id ? (
          <span className="text-muted-foreground">
            No person or device attributed with enough confidence
          </span>
        ) : null}
      </div>
    </div>
  );
}

function EvidenceBlock({ evidence }: { evidence: Record<string, unknown> }) {
  const keys = Object.keys(evidence);
  if (keys.length === 0) {
    return (
      <p className="rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground">
        No structured evidence recorded for this finding.
      </p>
    );
  }

  return (
    <dl className="divide-y rounded-lg border">
      {keys.map((key) => {
        const value = evidence[key];
        const display =
          typeof value === "string" ||
          typeof value === "number" ||
          typeof value === "boolean" ||
          value === null
            ? String(value)
            : JSON.stringify(value, null, 2);

        return (
          <div
            key={key}
            className="grid gap-1 px-4 py-3 sm:grid-cols-[10rem_1fr] sm:gap-4"
          >
            <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              {key.replaceAll("_", " ")}
            </dt>
            <dd className="min-w-0 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground">
              {display}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function FeedbackControls({ finding }: { finding: FindingOut }) {
  const feedback = useFindingFeedback();

  return (
    <section className="space-y-3">
      <div className="space-y-0.5">
        <h2 className="text-base font-semibold tracking-tight">Feedback</h2>
        <p className="text-sm text-muted-foreground">
          Classify this finding. Feedback updates status and can create a
          suppression for similar matches.
        </p>
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {FEEDBACK_ACTIONS.map((action) => (
          <div
            key={action.classification}
            className="flex flex-col gap-1.5 rounded-lg border px-3 py-3"
          >
            <Button
              type="button"
              size="sm"
              variant={action.variant}
              className="w-full justify-center sm:w-auto sm:self-start"
              disabled={feedback.isPending}
              onClick={() =>
                feedback.mutate({
                  findingId: finding.id,
                  classification: action.classification,
                })
              }
            >
              {feedback.isPending &&
              feedback.variables?.classification === action.classification
                ? "Saving…"
                : feedbackClassificationLabel(action.classification)}
            </Button>
            <p className="text-xs text-muted-foreground">{action.description}</p>
          </div>
        ))}
      </div>

      {feedback.isError ? (
        <p className="text-sm text-destructive" role="alert">
          {feedback.error instanceof Error
            ? feedback.error.message
            : "Couldn’t save feedback"}
        </p>
      ) : null}

      {feedback.isSuccess ? (
        <div
          className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 px-3 py-2 text-sm"
          role="status"
        >
          <p>
            Saved as{" "}
            <span className="font-medium">
              {feedbackClassificationLabel(feedback.data.classification)}
            </span>
            . Status is now{" "}
            <span className="font-medium">
              {findingStatusLabel(feedback.data.finding.status)}
            </span>
            .
          </p>
          {feedback.data.suppression_id ? (
            <p className="mt-1 text-muted-foreground">
              Similar findings will be suppressed.{" "}
              <Link
                href="/findings?view=suppressions"
                className="font-medium text-foreground underline-offset-4 hover:underline"
              >
                View suppressions
              </Link>
            </p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

export function FindingDetail({ findingId }: { findingId: string }) {
  const { data, error, isLoading, isError, isFetching, refetch } =
    useFinding(findingId);

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
              {data?.title ?? "Finding"}
            </h1>
            {data ? (
              <div className="flex flex-wrap items-center gap-2">
                <Badge
                  variant="outline"
                  className={cn(severityTone(data.severity))}
                >
                  {severityLabel(data.severity)}
                </Badge>
                <Badge variant="secondary">
                  {findingStatusLabel(data.status)}
                </Badge>
                <Badge variant="outline">
                  Confidence {findingConfidenceLabel(data.confidence)}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  Occurred {formatRelativeTime(data.occurred_at)}
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
          <p className="text-sm text-muted-foreground">
            DNS signals show lookups requested — not that anyone viewed specific
            content.
          </p>

          <Section title="What happened">
            <p className="text-sm leading-relaxed">{data.summary}</p>
          </Section>

          <Separator />

          <Section title="Why flagged">
            <p className="text-sm leading-relaxed">{data.why_flagged}</p>
          </Section>

          <Separator />

          <Section title="Who / what involved">
            <InvolvedSubject finding={data} />
          </Section>

          <Separator />

          <Section title="Evidence">
            <EvidenceBlock evidence={data.evidence ?? {}} />
          </Section>

          <Separator />

          <Section title="Confidence">
            <p className="text-sm leading-relaxed">
              Rule confidence:{" "}
              <span className="font-medium">
                {findingConfidenceLabel(data.confidence)}
              </span>
              . Attribution stays unattributed unless confidence is sufficient.
            </p>
          </Section>

          <Separator />

          <Section title="What may be missing">
            {(data.missing_info ?? []).length > 0 ? (
              <ul className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                {(data.missing_info ?? []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">
                No additional gaps called out for this finding.
              </p>
            )}
          </Section>

          <Separator />

          <Section title="Recommended action">
            <p className="text-sm leading-relaxed">{data.recommended_action}</p>
          </Section>

          <Separator />

          <FeedbackControls finding={data} />

          <p className="text-xs text-muted-foreground">
            Rule {data.rule_id} · logic {data.logic_version} · detected{" "}
            {formatRelativeTime(data.detected_at)}
          </p>
        </>
      ) : null}
    </div>
  );
}
