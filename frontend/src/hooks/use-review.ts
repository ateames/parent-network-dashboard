"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { ReviewListOut } from "@/lib/api/types";

export const reviewQueryKey = ["correlation", "review"] as const;

export function useReview() {
  return useQuery({
    queryKey: reviewQueryKey,
    queryFn: () => apiFetch<ReviewListOut>("/api/correlation/review"),
  });
}
