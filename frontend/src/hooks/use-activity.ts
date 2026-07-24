"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import type { ActivitySummaryOut } from "@/lib/api/types";

export type ActivitySubject =
  | { person: string; device?: never }
  | { device: string; person?: never };

export function activityQueryKey(
  subject: ActivitySubject | null,
  window = "24h",
) {
  return [
    "activity",
    subject?.person
      ? { person: subject.person }
      : subject?.device
        ? { device: subject.device }
        : null,
    window,
  ] as const;
}

export function useActivity(
  subject: ActivitySubject | null,
  window = "24h",
) {
  return useQuery({
    queryKey: activityQueryKey(subject, window),
    queryFn: () => {
      if (!subject) {
        throw new Error("Activity subject is required");
      }
      return apiFetch<ActivitySummaryOut>("/api/activity", {
        searchParams: {
          window,
          person: "person" in subject ? subject.person : undefined,
          device: "device" in subject ? subject.device : undefined,
          compare_baseline: true,
        },
      });
    },
    enabled: Boolean(subject),
  });
}
