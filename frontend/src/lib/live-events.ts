import type { StreamEvent } from "@/lib/api/types";

/** Max events kept in memory / rendered on the Live page. */
export const LIVE_EVENT_CAP = 100;

/** Backfill page size (must be ≤ backend max of 200). */
export const LIVE_EVENT_BACKFILL_LIMIT = 100;

export function compareStreamEventsNewestFirst(
  a: StreamEvent,
  b: StreamEvent,
): number {
  const byTime =
    new Date(b.occurred_at).getTime() - new Date(a.occurred_at).getTime();
  if (byTime !== 0) return byTime;
  return b.id.localeCompare(a.id);
}

/** Deduplicate by id, sort newest-first, and cap length. */
export function mergeStreamEvents(
  existing: readonly StreamEvent[],
  incoming: readonly StreamEvent[],
  cap: number = LIVE_EVENT_CAP,
): StreamEvent[] {
  const byId = new Map<string, StreamEvent>();
  for (const event of existing) {
    byId.set(event.id, event);
  }
  for (const event of incoming) {
    byId.set(event.id, event);
  }
  return Array.from(byId.values())
    .sort(compareStreamEventsNewestFirst)
    .slice(0, cap);
}
