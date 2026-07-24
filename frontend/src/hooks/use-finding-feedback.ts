"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type {
  FindingFeedbackClassification,
  FindingFeedbackOut,
  FindingOut,
} from "@/lib/api/types";

import { findingQueryKey } from "./use-finding";

type FeedbackVars = {
  findingId: string;
  classification: FindingFeedbackClassification;
};

export function useFindingFeedback() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ findingId, classification }: FeedbackVars) =>
      apiFetch<FindingFeedbackOut>(`/api/findings/${findingId}/feedback`, {
        method: "POST",
        body: { classification },
      }),
    onSuccess: (data, vars) => {
      queryClient.setQueryData<FindingOut>(
        findingQueryKey(vars.findingId),
        data.finding,
      );
    },
    onSettled: (_data, _error, vars) => {
      void queryClient.invalidateQueries({
        queryKey: findingQueryKey(vars.findingId),
      });
      void queryClient.invalidateQueries({ queryKey: ["findings"] });
      void queryClient.invalidateQueries({ queryKey: ["suppressions"] });
      void queryClient.invalidateQueries({
        queryKey: ["dashboard", "summary"],
      });
    },
  });
}
