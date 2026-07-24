"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { SuppressionListOut } from "@/lib/api/types";

export const suppressionsQueryKey = ["suppressions"] as const;

export function useSuppressions() {
  return useQuery({
    queryKey: suppressionsQueryKey,
    queryFn: () => apiFetch<SuppressionListOut>("/api/suppressions"),
  });
}
