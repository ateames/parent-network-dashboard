"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { PersonCreateIn, PersonListOut, PersonOut } from "@/lib/api/types";

import { personQueryKey } from "./use-person";

export const peopleQueryKey = ["people"] as const;

export function usePeople() {
  return useQuery({
    queryKey: peopleQueryKey,
    queryFn: () => apiFetch<PersonListOut>("/api/people"),
  });
}

export function useCreatePerson() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: PersonCreateIn) =>
      apiFetch<PersonOut>("/api/people", {
        method: "POST",
        body,
      }),
    onSuccess: (person) => {
      queryClient.setQueryData(personQueryKey(person.id), person);
      queryClient.setQueryData<PersonListOut>(peopleQueryKey, (previous) => {
        if (!previous) {
          return { people: [person] };
        }
        const without = previous.people.filter((p) => p.id !== person.id);
        return {
          people: [...without, person].sort((a, b) =>
            a.name.localeCompare(b.name),
          ),
        };
      });
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: peopleQueryKey });
    },
  });
}
