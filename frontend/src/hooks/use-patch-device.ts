"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { DeviceDetailOut, DevicePatchIn } from "@/lib/api/types";

import { deviceQueryKey } from "./use-device";

type PatchVars = {
  deviceId: string;
  patch: DevicePatchIn;
};

type MutationContext = {
  previousDevice: DeviceDetailOut | undefined;
};

export function usePatchDevice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ deviceId, patch }: PatchVars) =>
      apiFetch<DeviceDetailOut>(`/api/devices/${deviceId}`, {
        method: "PATCH",
        body: patch,
      }),
    onMutate: async ({ deviceId, patch }): Promise<MutationContext> => {
      const key = deviceQueryKey(deviceId);
      await queryClient.cancelQueries({ queryKey: key });
      const previousDevice = queryClient.getQueryData<DeviceDetailOut>(key);

      if (previousDevice) {
        queryClient.setQueryData<DeviceDetailOut>(key, {
          ...previousDevice,
          display_name:
            patch.display_name !== undefined
              ? patch.display_name
              : previousDevice.display_name,
          notes:
            patch.notes !== undefined ? patch.notes : previousDevice.notes,
        });
      }

      return { previousDevice };
    },
    onError: (_error, vars, context) => {
      if (context?.previousDevice) {
        queryClient.setQueryData(
          deviceQueryKey(vars.deviceId),
          context.previousDevice,
        );
      }
    },
    onSuccess: (data, vars) => {
      queryClient.setQueryData(deviceQueryKey(vars.deviceId), data);
    },
    onSettled: (_data, _error, vars) => {
      void queryClient.invalidateQueries({
        queryKey: deviceQueryKey(vars.deviceId),
      });
      void queryClient.invalidateQueries({ queryKey: ["devices"] });
      void queryClient.invalidateQueries({ queryKey: ["people"] });
    },
  });
}
