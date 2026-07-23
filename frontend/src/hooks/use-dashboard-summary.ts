"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { DashboardSummary } from "@/lib/api/types";

export const dashboardSummaryQueryKey = ["dashboard", "summary"] as const;

export function useDashboardSummary() {
  return useQuery({
    queryKey: dashboardSummaryQueryKey,
    queryFn: () => apiFetch<DashboardSummary>("/api/dashboard/summary"),
    refetchInterval: 30_000,
  });
}
