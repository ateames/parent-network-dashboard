"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { SystemHealthOut } from "@/lib/api/types";

export function useSystemHealth() {
  return useQuery({
    queryKey: ["system-health"],
    queryFn: () => apiFetch<SystemHealthOut>("/api/system/health"),
    refetchInterval: 15_000,
  });
}
