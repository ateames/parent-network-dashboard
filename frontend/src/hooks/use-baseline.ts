"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { BaselineOut } from "@/lib/api/types";

export function baselineQueryKey(subjectId: string, window = "24h") {
  return ["baselines", subjectId, window] as const;
}

export function useBaseline(subjectId: string | null, window = "24h") {
  return useQuery({
    queryKey: baselineQueryKey(subjectId ?? "", window),
    queryFn: () =>
      apiFetch<BaselineOut>(`/api/baselines/${subjectId}`, {
        searchParams: { window },
      }),
    enabled: Boolean(subjectId),
  });
}
