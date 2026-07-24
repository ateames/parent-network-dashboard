"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { PersonOut } from "@/lib/api/types";

export function personQueryKey(personId: string) {
  return ["people", personId] as const;
}

export function usePerson(personId: string | null) {
  return useQuery({
    queryKey: personQueryKey(personId ?? ""),
    queryFn: () => apiFetch<PersonOut>(`/api/people/${personId}`),
    enabled: Boolean(personId),
  });
}
