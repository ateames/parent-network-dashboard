"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { FindingOut } from "@/lib/api/types";

export function findingQueryKey(findingId: string) {
  return ["finding", findingId] as const;
}

export function useFinding(findingId: string) {
  return useQuery({
    queryKey: findingQueryKey(findingId),
    queryFn: () => apiFetch<FindingOut>(`/api/findings/${findingId}`),
    enabled: Boolean(findingId),
  });
}
