"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";

import { suppressionsQueryKey } from "./use-suppressions";

export function useDeleteSuppression() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (suppressionId: string) =>
      apiFetch<null>(`/api/suppressions/${suppressionId}`, {
        method: "DELETE",
      }),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: suppressionsQueryKey });
      void queryClient.invalidateQueries({ queryKey: ["findings"] });
    },
  });
}
