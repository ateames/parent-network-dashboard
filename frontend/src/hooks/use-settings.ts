"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type {
  ConnectionTestIn,
  ConnectionTestOut,
  ConnectionsOut,
  ConnectionsPutIn,
  ExpectedActivityScheduleIn,
  ExpectedActivityScheduleOut,
  ExpectedActivitySchedulePatchIn,
  LocalSettingsOut,
  SetupStatusOut,
  ThresholdsPatchIn,
} from "@/lib/api/types";

export function useLocalSettings() {
  return useQuery({
    queryKey: ["local-settings"],
    queryFn: () => apiFetch<LocalSettingsOut>("/api/settings"),
  });
}

export function useSetupStatus(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["setup-status"],
    queryFn: () => apiFetch<SetupStatusOut>("/api/settings/setup-status"),
    enabled: options?.enabled ?? true,
    retry: 2,
  });
}

export function useConnections() {
  return useQuery({
    queryKey: ["connections"],
    queryFn: () => apiFetch<ConnectionsOut>("/api/settings/connections"),
  });
}

export function usePutConnections() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectionsPutIn) =>
      apiFetch<ConnectionsOut>("/api/settings/connections", {
        method: "PUT",
        body,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["connections"] });
      await queryClient.invalidateQueries({ queryKey: ["setup-status"] });
    },
  });
}

export function useTestPihole() {
  return useMutation({
    mutationFn: (body: ConnectionTestIn) =>
      apiFetch<ConnectionTestOut>("/api/settings/connections/test/pihole", {
        method: "POST",
        body,
      }),
  });
}

export function useTestUnifi() {
  return useMutation({
    mutationFn: (body: ConnectionTestIn) =>
      apiFetch<ConnectionTestOut>("/api/settings/connections/test/unifi", {
        method: "POST",
        body,
      }),
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
