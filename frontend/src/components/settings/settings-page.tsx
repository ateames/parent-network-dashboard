"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { useDevices } from "@/hooks/use-devices";
import { usePeople } from "@/hooks/use-people";
import {
  useCreateSchedule,
  useDeleteSchedule,
  useLocalSettings,
  usePatchSchedule,
  usePatchThresholds,
} from "@/hooks/use-settings";
import type {
  ExpectedActivityScheduleOut,
  ThresholdsOut,
} from "@/lib/api/types";
import { deviceDisplayName, formatDateTime } from "@/lib/format";

const fieldClassName =
  "flex h-9 w-full rounded-lg border border-input bg-background px-2.5 text-sm outline-none transition-colors focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:opacity-50";

const selectClassName = fieldClassName;

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
const DAYS = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" },
];

function ThresholdsForm({ thresholds }: { thresholds: ThresholdsOut }) {
  const patch = usePatchThresholds();
  const [form, setForm] = useState(thresholds);

  useEffect(() => {
    setForm(thresholds);
  }, [thresholds]);

  const dirty =
    form.correlation_confidence_threshold !==
      thresholds.correlation_confidence_threshold ||
    form.source_health_stale_seconds !== thresholds.source_health_stale_seconds ||
    form.source_health_max_failures !== thresholds.source_health_max_failures ||
    form.pihole_poll_interval_seconds !==
      thresholds.pihole_poll_interval_seconds ||
    form.unifi_poll_interval_seconds !==
      thresholds.unifi_poll_interval_seconds ||
    form.baseline_z_threshold !== thresholds.baseline_z_threshold;

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    patch.mutate({
      correlation_confidence_threshold: form.correlation_confidence_threshold,
      source_health_stale_seconds: form.source_health_stale_seconds,
      source_health_max_failures: form.source_health_max_failures,
      pihole_poll_interval_seconds: form.pihole_poll_interval_seconds,
      unifi_poll_interval_seconds: form.unifi_poll_interval_seconds,
      baseline_z_threshold: form.baseline_z_threshold,
    });
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded-lg border p-4">
      <div className="space-y-1">
        <h2 className="text-base font-semibold tracking-tight">Thresholds</h2>
        <p className="text-sm text-muted-foreground">
          Correlation confidence, staleness windows, poll intervals, and
          baseline sensitivity. Changes are audited.
        </p>
        {thresholds.updated_at ? (
          <p className="text-xs text-muted-foreground">
            Last updated {formatDateTime(thresholds.updated_at)}
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">
            Showing env defaults until saved once.
          </p>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Correlation confidence</span>
          <input
            type="number"
            min={0}
            max={1}
            step={0.01}
            className={fieldClassName}
            value={form.correlation_confidence_threshold}
            onChange={(event) =>
              setForm((prev) => ({
                ...prev,
                correlation_confidence_threshold: Number(event.target.value),
              }))
            }
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Baseline sensitivity (z)</span>
          <input
            type="number"
            min={0.5}
            max={10}
            step={0.1}
            className={fieldClassName}
            value={form.baseline_z_threshold}
            onChange={(event) =>
              setForm((prev) => ({
                ...prev,
                baseline_z_threshold: Number(event.target.value),
              }))
            }
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Source stale window (seconds)</span>
          <input
            type="number"
            min={30}
            max={86400}
            className={fieldClassName}
            value={form.source_health_stale_seconds}
            onChange={(event) =>
              setForm((prev) => ({
                ...prev,
                source_health_stale_seconds: Number(event.target.value),
              }))
            }
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Max consecutive failures</span>
          <input
            type="number"
            min={1}
            max={100}
            className={fieldClassName}
            value={form.source_health_max_failures}
            onChange={(event) =>
              setForm((prev) => ({
                ...prev,
                source_health_max_failures: Number(event.target.value),
              }))
            }
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Pi-hole poll interval (seconds)</span>
          <input
            type="number"
            min={5}
            max={3600}
            className={fieldClassName}
            value={form.pihole_poll_interval_seconds}
            onChange={(event) =>
              setForm((prev) => ({
                ...prev,
                pihole_poll_interval_seconds: Number(event.target.value),
              }))
            }
          />
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">UniFi poll interval (seconds)</span>
          <input
            type="number"
            min={5}
            max={3600}
            className={fieldClassName}
            value={form.unifi_poll_interval_seconds}
            onChange={(event) =>
              setForm((prev) => ({
                ...prev,
                unifi_poll_interval_seconds: Number(event.target.value),
              }))
            }
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" size="sm" disabled={!dirty || patch.isPending}>
          {patch.isPending ? "Saving…" : "Save thresholds"}
        </Button>
        {dirty ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={patch.isPending}
            onClick={() => setForm(thresholds)}
          >
            Reset
          </Button>
        ) : null}
      </div>
      {patch.isError ? (
        <p className="text-sm text-destructive" role="alert">
          {patch.error instanceof Error
            ? patch.error.message
            : "Couldn’t save thresholds"}
        </p>
      ) : null}
      {patch.isSuccess && !dirty ? (
        <p className="text-sm text-emerald-700 dark:text-emerald-400">
          Thresholds saved.
        </p>
      ) : null}
    </form>
  );
}

function HourPicker({
  selected,
  onChange,
}: {
  selected: number[];
  onChange: (hours: number[]) => void;
}) {
  const set = useMemo(() => new Set(selected), [selected]);
  return (
    <div className="grid grid-cols-6 gap-1.5 sm:grid-cols-8 md:grid-cols-12">
      {HOURS.map((hour) => {
        const active = set.has(hour);
        return (
          <button
            key={hour}
            type="button"
            className={
              active
                ? "rounded-md bg-foreground px-1 py-1.5 text-xs font-medium text-background"
                : "rounded-md border px-1 py-1.5 text-xs text-muted-foreground hover:bg-muted/60"
            }
            onClick={() => {
              const next = new Set(set);
              if (next.has(hour)) next.delete(hour);
              else next.add(hour);
              onChange(Array.from(next).sort((a, b) => a - b));
            }}
          >
            {String(hour).padStart(2, "0")}
          </button>
        );
      })}
    </div>
  );
}

function DayPicker({
  selected,
  onChange,
}: {
  selected: number[] | null;
  onChange: (days: number[] | null) => void;
}) {
  const set = useMemo(() => new Set(selected ?? []), [selected]);
  const allDays = selected == null;

  return (
    <div className="space-y-2">
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={allDays}
          onChange={(event) => onChange(event.target.checked ? null : [])}
        />
        Every day
      </label>
      {!allDays ? (
        <div className="flex flex-wrap gap-1.5">
          {DAYS.map((day) => {
            const active = set.has(day.value);
            return (
              <button
                key={day.value}
                type="button"
                className={
                  active
                    ? "rounded-md bg-foreground px-2.5 py-1.5 text-xs font-medium text-background"
                    : "rounded-md border px-2.5 py-1.5 text-xs text-muted-foreground hover:bg-muted/60"
                }
                onClick={() => {
                  const next = new Set(set);
                  if (next.has(day.value)) next.delete(day.value);
                  else next.add(day.value);
                  onChange(Array.from(next).sort((a, b) => a - b));
                }}
              >
                {day.label}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

function ScheduleCard({ schedule }: { schedule: ExpectedActivityScheduleOut }) {
  const patch = usePatchSchedule();
  const remove = useDeleteSchedule();
  const people = usePeople();
  const devices = useDevices();

  const subjectLabel = useMemo(() => {
    if (schedule.person_id) {
      const person = people.data?.people.find((p) => p.id === schedule.person_id);
      return person ? person.name : `Person ${schedule.person_id.slice(0, 8)}`;
    }
    if (schedule.device_id) {
      const device = devices.data?.devices.find((d) => d.id === schedule.device_id);
      return device
        ? deviceDisplayName(device)
        : `Device ${schedule.device_id.slice(0, 8)}`;
    }
    return "Unknown";
  }, [devices.data?.devices, people.data?.people, schedule.device_id, schedule.person_id]);

  return (
    <article className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h3 className="text-sm font-semibold tracking-tight">
            {schedule.label || subjectLabel}
          </h3>
          <p className="text-xs text-muted-foreground">
            {schedule.person_id ? "Person" : "Device"} · {subjectLabel}
          </p>
        </div>
        <Badge variant="outline">{schedule.active ? "Active" : "Inactive"}</Badge>
      </div>
      <p className="text-sm text-muted-foreground">
        Hours (UTC):{" "}
        {schedule.expected_hours_utc
          .map((h) => String(h).padStart(2, "0"))
          .join(", ")}
      </p>
      <p className="text-sm text-muted-foreground">
        Days:{" "}
        {schedule.days_of_week == null
          ? "Every day"
          : schedule.days_of_week
              .map((d) => DAYS.find((x) => x.value === d)?.label ?? d)
              .join(", ")}
      </p>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={patch.isPending}
          onClick={() =>
            patch.mutate({
              scheduleId: schedule.id,
              patch: { active: !schedule.active },
            })
          }
        >
          {schedule.active ? "Deactivate" : "Activate"}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={remove.isPending}
          onClick={() => {
            if (window.confirm("Delete this schedule?")) {
              remove.mutate(schedule.id);
            }
          }}
        >
          Delete
        </Button>
      </div>
    </article>
  );
}

function CreateScheduleForm() {
  const create = useCreateSchedule();
  const people = usePeople();
  const devices = useDevices();
  const [subjectType, setSubjectType] = useState<"person" | "device">("person");
  const [subjectId, setSubjectId] = useState("");
  const [label, setLabel] = useState("");
  const [hours, setHours] = useState<number[]>([8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20]);
  const [days, setDays] = useState<number[] | null>(null);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!subjectId || hours.length === 0) return;
    create.mutate(
      {
        person_id: subjectType === "person" ? subjectId : null,
        device_id: subjectType === "device" ? subjectId : null,
        label: label.trim() || null,
        expected_hours_utc: hours,
        days_of_week: days,
        active: true,
      },
      {
        onSuccess: () => {
          setLabel("");
          setSubjectId("");
        },
      },
    );
  }

  const options =
    subjectType === "person"
      ? (people.data?.people ?? []).map((p) => ({
          id: p.id,
          label: p.name,
        }))
      : (devices.data?.devices ?? []).map((d) => ({
          id: d.id,
          label: deviceDisplayName(d),
        }));

  return (
    <form onSubmit={onSubmit} className="space-y-4 rounded-lg border p-4">
      <div className="space-y-1">
        <h3 className="text-sm font-semibold tracking-tight">
          Add expected-activity schedule
        </h3>
        <p className="text-sm text-muted-foreground">
          Used by the “outside expected hours” finding rule. Prefer a household
          schedule over statistical typical hours when present.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">Subject type</span>
          <select
            className={selectClassName}
            value={subjectType}
            onChange={(event) => {
              setSubjectType(event.target.value as "person" | "device");
              setSubjectId("");
            }}
          >
            <option value="person">Person</option>
            <option value="device">Device</option>
          </select>
        </label>
        <label className="space-y-1.5 text-sm">
          <span className="font-medium">
            {subjectType === "person" ? "Person" : "Device"}
          </span>
          <select
            className={selectClassName}
            value={subjectId}
            onChange={(event) => setSubjectId(event.target.value)}
            required
          >
            <option value="">Select…</option>
            {options.map((opt) => (
              <option key={opt.id} value={opt.id}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="block space-y-1.5 text-sm">
        <span className="font-medium">Label (optional)</span>
        <input
          className={fieldClassName}
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          placeholder="School nights"
        />
      </label>

      <div className="space-y-1.5">
        <p className="text-sm font-medium">Expected hours (UTC)</p>
        <HourPicker selected={hours} onChange={setHours} />
      </div>

      <div className="space-y-1.5">
        <p className="text-sm font-medium">Days of week</p>
        <DayPicker selected={days} onChange={setDays} />
      </div>

      <Button
        type="submit"
        size="sm"
        disabled={
          create.isPending || !subjectId || hours.length === 0 || (days !== null && days.length === 0)
        }
      >
        {create.isPending ? "Creating…" : "Create schedule"}
      </Button>
      {create.isError ? (
        <p className="text-sm text-destructive" role="alert">
          {create.error instanceof Error
            ? create.error.message
            : "Couldn’t create schedule"}
        </p>
      ) : null}
    </form>
  );
}

export function SettingsPage() {
  const settings = useLocalSettings();

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Local analysis thresholds and expected-activity schedules. Credentials
          for Pi-hole/UniFi stay in server env — never in the browser.
        </p>
      </div>

      {settings.isLoading ? (
        <div className="space-y-3" aria-busy>
          <div className="h-48 animate-pulse rounded-lg bg-muted" />
          <div className="h-40 animate-pulse rounded-lg bg-muted/70" />
        </div>
      ) : null}

      {settings.isError ? (
        <div
          className="rounded-lg border border-destructive/40 bg-destructive/5 px-4 py-6"
          role="alert"
        >
          <p className="text-sm font-semibold text-destructive">
            Couldn’t load settings
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {settings.error instanceof Error
              ? settings.error.message
              : "Request failed"}
          </p>
        </div>
      ) : null}

      {settings.data ? (
        <>
          <ThresholdsForm thresholds={settings.data.thresholds} />
          <Separator />
          <section className="space-y-4">
            <div className="space-y-1">
              <h2 className="text-base font-semibold tracking-tight">
                Expected-activity schedules
              </h2>
              <p className="text-sm text-muted-foreground">
                Parent-defined hours used by the outside-expected-hours rule.
              </p>
            </div>
            <CreateScheduleForm />
            {settings.data.schedules.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No schedules yet. Until you add one, the rule uses statistical
                typical hours from baselines.
              </p>
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {settings.data.schedules.map((schedule) => (
                  <ScheduleCard key={schedule.id} schedule={schedule} />
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}
