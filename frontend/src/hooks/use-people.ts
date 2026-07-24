"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { PersonListOut } from "@/lib/api/types";

export const peopleQueryKey = ["people"] as const;

export function usePeople() {
  return useQuery({
    queryKey: peopleQueryKey,
    queryFn: () => apiFetch<PersonListOut>("/api/people"),
  });
}
