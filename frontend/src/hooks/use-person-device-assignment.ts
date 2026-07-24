"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type {
  AssignedDeviceOut,
  PersonDeviceOut,
  PersonOut,
} from "@/lib/api/types";

import { peopleQueryKey } from "./use-people";
import { personQueryKey } from "./use-person";

type AssignVars = {
  personId: string;
  deviceId: string;
  device?: Pick<AssignedDeviceOut, "id" | "display_name">;
};

type UnassignVars = {
  personId: string;
  deviceId: string;
};

type MutationContext = {
  previousPerson: PersonOut | undefined;
};

function invalidateAssignmentQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  personId: string,
) {
  void queryClient.invalidateQueries({ queryKey: personQueryKey(personId) });
  void queryClient.invalidateQueries({ queryKey: peopleQueryKey });
  void queryClient.invalidateQueries({ queryKey: ["devices"] });
}

export function useAssignDevice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ personId, deviceId }: AssignVars) =>
      apiFetch<PersonDeviceOut>(`/api/people/${personId}/devices`, {
        method: "POST",
        body: { device_id: deviceId },
      }),
    onMutate: async ({ personId, deviceId, device }): Promise<MutationContext> => {
      const key = personQueryKey(personId);
      await queryClient.cancelQueries({ queryKey: key });
      const previousPerson = queryClient.getQueryData<PersonOut>(key);

      if (previousPerson) {
        const optimisticDevice: AssignedDeviceOut = {
          id: deviceId,
          display_name: device?.display_name ?? null,
          assigned_at: new Date().toISOString(),
          assigned_by: "you",
        };
        const withoutDevice = (previousPerson.devices ?? []).filter(
          (d) => d.id !== deviceId,
        );
        queryClient.setQueryData<PersonOut>(key, {
          ...previousPerson,
          devices: [...withoutDevice, optimisticDevice],
        });
      }

      return { previousPerson };
    },
    onError: (_error, vars, context) => {
      if (context?.previousPerson) {
        queryClient.setQueryData(
          personQueryKey(vars.personId),
          context.previousPerson,
        );
      }
    },
    onSettled: (_data, _error, vars) => {
      invalidateAssignmentQueries(queryClient, vars.personId);
    },
  });
}

export function useUnassignDevice() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ personId, deviceId }: UnassignVars) =>
      apiFetch<null>(`/api/people/${personId}/devices/${deviceId}`, {
        method: "DELETE",
      }),
    onMutate: async ({ personId, deviceId }): Promise<MutationContext> => {
      const key = personQueryKey(personId);
      await queryClient.cancelQueries({ queryKey: key });
      const previousPerson = queryClient.getQueryData<PersonOut>(key);

      if (previousPerson) {
        queryClient.setQueryData<PersonOut>(key, {
          ...previousPerson,
          devices: (previousPerson.devices ?? []).filter((d) => d.id !== deviceId),
        });
      }

      return { previousPerson };
    },
    onError: (_error, vars, context) => {
      if (context?.previousPerson) {
        queryClient.setQueryData(
          personQueryKey(vars.personId),
          context.previousPerson,
        );
      }
    },
    onSettled: (_data, _error, vars) => {
      invalidateAssignmentQueries(queryClient, vars.personId);
    },
  });
}
