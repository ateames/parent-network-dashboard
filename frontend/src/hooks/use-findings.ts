"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type {
  FindingListOut,
  FindingSeverity,
  FindingStatus,
} from "@/lib/api/types";

export type FindingListFilters = {
  severity?: FindingSeverity | null;
  person?: string | null;
  device?: string | null;
  status?: FindingStatus | null;
  limit?: number;
};

export function findingsQueryKey(filters: FindingListFilters = {}) {
  return [
    "findings",
    {
      severity: filters.severity ?? null,
      person: filters.person ?? null,
      device: filters.device ?? null,
      status: filters.status ?? null,
      limit: filters.limit ?? 100,
    },
  ] as const;
}

export function useFindings(filters: FindingListFilters = {}) {
  return useQuery({
    queryKey: findingsQueryKey(filters),
    queryFn: () =>
      apiFetch<FindingListOut>("/api/findings", {
        searchParams: {
          severity: filters.severity ?? undefined,
          person: filters.person ?? undefined,
          device: filters.device ?? undefined,
          status: filters.status ?? undefined,
          limit: filters.limit ?? 100,
        },
      }),
  });
}
