"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type {
  DeviceDetailOut,
  InternetRestrictionCreateIn,
} from "@/lib/api/types";

import { deviceQueryKey } from "./use-device";

type CreateVars = {
  deviceId: string;
  body: InternetRestrictionCreateIn;
};

type DeleteVars = {
  deviceId: string;
};

export function useCreateInternetRestriction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ deviceId, body }: CreateVars) =>
      apiFetch<DeviceDetailOut>(
        `/api/devices/${deviceId}/internet-restriction`,
        {
          method: "POST",
          body,
        },
      ),
    onSuccess: (data, vars) => {
      queryClient.setQueryData(deviceQueryKey(vars.deviceId), data);
    },
    onSettled: (_data, _error, vars) => {
      void queryClient.invalidateQueries({
        queryKey: deviceQueryKey(vars.deviceId),
      });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
    },
  });
}

export function useDeleteInternetRestriction() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ deviceId }: DeleteVars) =>
      apiFetch<DeviceDetailOut>(
        `/api/devices/${deviceId}/internet-restriction`,
        {
          method: "DELETE",
        },
      ),
    onSuccess: (data, vars) => {
      queryClient.setQueryData(deviceQueryKey(vars.deviceId), data);
    },
    onSettled: (_data, _error, vars) => {
      void queryClient.invalidateQueries({
        queryKey: deviceQueryKey(vars.deviceId),
      });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
    },
  });
}
