"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type {
  CorrelationResolveIn,
  CorrelationResolveOut,
  ReviewListOut,
} from "@/lib/api/types";

import { reviewQueryKey } from "./use-review";

export type ResolveReviewVars = {
  activityId: string;
} & (
  | {
      leaveUnattributed: true;
    }
  | {
      leaveUnattributed?: false;
      deviceId: string;
      strengthenIdentifier?: boolean;
    }
);

type MutationContext = {
  previous: ReviewListOut | undefined;
};

function toBody(vars: ResolveReviewVars): CorrelationResolveIn {
  if (vars.leaveUnattributed) {
    return {
      leave_unattributed: true,
      strengthen_identifier: false,
      device_id: null,
    };
  }
  return {
    device_id: vars.deviceId,
    leave_unattributed: false,
    strengthen_identifier: vars.strengthenIdentifier ?? false,
  };
}

export function useResolveReview() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (vars: ResolveReviewVars) =>
      apiFetch<CorrelationResolveOut>(
        `/api/correlation/review/${vars.activityId}/resolve`,
        {
          method: "POST",
          body: toBody(vars),
        },
      ),
    onMutate: async (vars): Promise<MutationContext> => {
      await queryClient.cancelQueries({ queryKey: reviewQueryKey });
      const previous = queryClient.getQueryData<ReviewListOut>(reviewQueryKey);

      if (previous) {
        queryClient.setQueryData<ReviewListOut>(reviewQueryKey, {
          items: previous.items.filter((item) => item.id !== vars.activityId),
        });
      }

      return { previous };
    },
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(reviewQueryKey, context.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: reviewQueryKey });
      void queryClient.invalidateQueries({
        queryKey: ["dashboard", "summary"],
      });
    },
  });
}
