"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type {
  ExpectedActivityScheduleIn,
  ExpectedActivityScheduleOut,
  ExpectedActivitySchedulePatchIn,
  LocalSettingsOut,
  ThresholdsPatchIn,
} from "@/lib/api/types";

export function useLocalSettings() {
  return useQuery({
    queryKey: ["local-settings"],
    queryFn: () => apiFetch<LocalSettingsOut>("/api/settings"),
  });
}

export function usePatchThresholds() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch: ThresholdsPatchIn) =>
      apiFetch("/api/settings/thresholds", {
        method: "PATCH",
        body: patch,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["local-settings"] });
    },
  });
}

export function useCreateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ExpectedActivityScheduleIn) =>
      apiFetch<ExpectedActivityScheduleOut>("/api/settings/schedules", {
        method: "POST",
        body,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["local-settings"] });
    },
  });
}

export function usePatchSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      scheduleId,
      patch,
    }: {
      scheduleId: string;
      patch: ExpectedActivitySchedulePatchIn;
    }) =>
      apiFetch<ExpectedActivityScheduleOut>(
        `/api/settings/schedules/${scheduleId}`,
        {
          method: "PATCH",
          body: patch,
        },
      ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["local-settings"] });
    },
  });
}

export function useDeleteSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId: string) =>
      apiFetch<void>(`/api/settings/schedules/${scheduleId}`, {
        method: "DELETE",
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["local-settings"] });
    },
  });
}
