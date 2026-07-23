"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useHealth } from "@/hooks/use-health";
import { cn } from "@/lib/utils";

export function HealthStatus() {
  const { data, error, isFetching, isLoading, refetch, isError } = useHealth();
  const healthy = !isError && data?.status === "ok";

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <span
          className={cn(
            "inline-block size-3 rounded-full",
            isLoading
              ? "bg-muted-foreground/40"
              : healthy
                ? "bg-emerald-500"
                : "bg-red-500",
          )}
          aria-hidden
        />
        <Badge
          variant="outline"
          className={cn(
            healthy &&
              "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
            !isLoading &&
              !healthy &&
              "border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-400",
          )}
        >
          {isLoading
            ? "Checking…"
            : healthy
              ? "API healthy"
              : "API unreachable"}
        </Badge>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void refetch()}
          disabled={isFetching}
        >
          {isFetching ? "Refreshing…" : "Refresh"}
        </Button>
      </div>

      <p className="text-sm text-muted-foreground">
        Status is loaded via{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-xs">
          /api/proxy/health
        </code>
        , which forwards to the backend with the server-only admin token.
      </p>

      {healthy && data ? (
        <pre className="overflow-x-auto rounded-md border bg-muted/40 p-3 text-xs">
          {JSON.stringify(data, null, 2)}
        </pre>
      ) : null}

      {isError ? (
        <p className="text-sm text-destructive" role="alert">
          {error instanceof Error ? error.message : "Health check failed"}
        </p>
      ) : null}
    </div>
  );
}
