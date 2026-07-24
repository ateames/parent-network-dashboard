"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { SourceHealthListOut } from "@/lib/api/types";

export function useSourceHealth() {
  return useQuery({
    queryKey: ["source-health"],
    queryFn: () => apiFetch<SourceHealthListOut>("/api/sources/health"),
    refetchInterval: 15_000,
  });
}
