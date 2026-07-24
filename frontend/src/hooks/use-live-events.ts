"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { apiFetch, apiProxyUrl } from "@/lib/api/client";
import type { StreamEvent, StreamEventList } from "@/lib/api/types";
import {
  LIVE_EVENT_BACKFILL_LIMIT,
  LIVE_EVENT_CAP,
  mergeStreamEvents,
} from "@/lib/live-events";

export const liveEventsQueryKey = ["events", "recent"] as const;

export type LiveConnectionStatus = "connecting" | "live" | "reconnecting";

const STREAM_PATH = "/api/events/stream";
const MIN_RETRY_MS = 1_000;
const MAX_RETRY_MS = 30_000;

function isStreamEvent(value: unknown): value is StreamEvent {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    typeof record.kind === "string" &&
    typeof record.severity === "string" &&
    typeof record.summary === "string" &&
    typeof record.occurred_at === "string"
  );
}

async function fetchRecentFromApi(): Promise<StreamEvent[]> {
  const body = await apiFetch<StreamEventList>("/api/events/recent", {
    searchParams: { limit: LIVE_EVENT_BACKFILL_LIMIT },
  });
  return body.items ?? [];
}

export function useLiveEvents() {
  const queryClient = useQueryClient();
  const [connectionStatus, setConnectionStatus] =
    useState<LiveConnectionStatus>("connecting");

  const query = useQuery({
    queryKey: liveEventsQueryKey,
    queryFn: async () => {
      const incoming = await fetchRecentFromApi();
      // Merge with any SSE events that arrived while the request was in flight.
      const current =
        queryClient.getQueryData<StreamEvent[]>(liveEventsQueryKey) ?? [];
      return mergeStreamEvents(current, incoming, LIVE_EVENT_CAP);
    },
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchInterval: false,
  });

  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryMs = MIN_RETRY_MS;
    let hasOpened = false;
    let refillOnNextOpen = false;

    const clearRetry = () => {
      if (retryTimer != null) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
    };

    const applyIncoming = (incoming: StreamEvent[]) => {
      queryClient.setQueryData<StreamEvent[]>(liveEventsQueryKey, (current) =>
        mergeStreamEvents(current ?? [], incoming, LIVE_EVENT_CAP),
      );
    };

    const refillAfterGap = () => {
      void fetchRecentFromApi()
        .then((items) => {
          if (!disposed) applyIncoming(items);
        })
        .catch(() => {
          // Backfill best-effort; stream reconnect still proceeds.
        });
    };

    const scheduleReconnect = () => {
      if (disposed) return;
      clearRetry();
      setConnectionStatus(hasOpened ? "reconnecting" : "connecting");
      retryTimer = setTimeout(() => {
        retryTimer = null;
        connect();
      }, retryMs);
      retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
    };

    const connect = () => {
      if (disposed) return;
      clearRetry();
      source?.close();
      source = null;

      setConnectionStatus(hasOpened ? "reconnecting" : "connecting");
      const next = new EventSource(apiProxyUrl(STREAM_PATH));
      source = next;

      next.addEventListener("stream", (message: MessageEvent<string>) => {
        try {
          const parsed: unknown = JSON.parse(message.data);
          if (!isStreamEvent(parsed)) return;
          applyIncoming([parsed]);
        } catch {
          // Ignore malformed frames.
        }
      });

      next.onopen = () => {
        if (disposed || source !== next) return;
        hasOpened = true;
        retryMs = MIN_RETRY_MS;
        setConnectionStatus("live");
        if (refillOnNextOpen) {
          refillOnNextOpen = false;
          refillAfterGap();
        }
      };

      next.onerror = () => {
        if (disposed || source !== next) return;
        next.close();
        if (source === next) source = null;
        refillOnNextOpen = true;
        scheduleReconnect();
      };
    };

    connect();

    return () => {
      disposed = true;
      clearRetry();
      source?.close();
      source = null;
    };
  }, [queryClient]);

  return {
    ...query,
    events: query.data ?? [],
    connectionStatus,
  };
}