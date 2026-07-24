"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { DeviceDetailOut } from "@/lib/api/types";

export function deviceQueryKey(deviceId: string) {
  return ["devices", deviceId] as const;
}

export function useDevice(deviceId: string | null) {
  return useQuery({
    queryKey: deviceQueryKey(deviceId ?? ""),
    queryFn: () => apiFetch<DeviceDetailOut>(`/api/devices/${deviceId}`),
    enabled: Boolean(deviceId),
  });
}
