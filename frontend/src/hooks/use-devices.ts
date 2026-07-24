"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { DeviceListOut } from "@/lib/api/types";

export type DeviceListFilters = {
  online?: boolean;
  unknown?: boolean;
  unassigned?: boolean;
};

export function devicesQueryKey(filters: DeviceListFilters = {}) {
  return [
    "devices",
    {
      online: filters.online ?? null,
      unknown: filters.unknown ?? null,
      unassigned: filters.unassigned ?? null,
    },
  ] as const;
}

export function useDevices(filters: DeviceListFilters = {}) {
  return useQuery({
    queryKey: devicesQueryKey(filters),
    queryFn: () =>
      apiFetch<DeviceListOut>("/api/devices", {
        searchParams: {
          online: filters.online,
          unknown: filters.unknown,
          unassigned: filters.unassigned,
        },
      }),
  });
}
