/** Small display helpers for parent-facing timestamps and labels. */

const relativeFmt = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

const SOURCE_LABELS: Record<string, string> = {
  pihole_api: "Pi-hole",
  unifi_api: "UniFi",
  unifi_syslog: "Syslog",
};

const ATTENTION_LABELS: Record<string, string> = {
  source_down: "Source down",
  source_degraded: "Source degraded",
  correlation_review: "Needs review",
  unknown_device: "Unknown device",
  unassigned_device: "Unassigned device",
};

const ACTIVITY_LABELS: Record<string, string> = {
  blocked_dns: "Blocked DNS",
  correlation_review: "Needs review",
  attributed_dns: "Attributed activity",
};

const STREAM_EVENT_LABELS: Record<string, string> = {
  new_device_joined: "New device",
  unknown_device_online: "Unknown device",
  blocked_query_burst: "Blocked DNS burst",
  dns_volume_increase: "DNS volume increase",
  activity_outside_expected_hours: "Outside expected hours",
  new_domain_burst: "New domain burst",
  connection_flapping: "Connection flapping",
  unifi_security_event: "UniFi security",
  source_data_loss: "Source data loss",
};

const SEVERITY_LABELS: Record<string, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
  info: "Info",
};

const FINDING_STATUS_LABELS: Record<string, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
  dismissed: "Dismissed",
};

const FINDING_CONFIDENCE_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
};

const FEEDBACK_CLASSIFICATION_LABELS: Record<string, string> = {
  expected: "Expected",
  concerning: "Concerning",
  incorrect: "Incorrect",
  ignore_once: "Ignore once",
  suppress_similar: "Suppress similar",
  needs_investigation: "Needs investigation",
  acknowledge: "Acknowledge",
  resolve: "Resolve",
};

const CORRELATION_STATUS_LABELS: Record<string, string> = {
  attributed: "Attributed",
  ambiguous: "Ambiguous",
  unattributed: "Unattributed",
};

const CONFLICT_REASON_LABELS: Record<string, string> = {
  multiple_candidate_devices: "Multiple candidate devices",
  ip_reassigned_in_window: "IP reassigned in window",
};

const EVIDENCE_KIND_LABELS: Record<string, string> = {
  ip_assignment: "IP assignment",
  pihole_client: "Pi-hole client",
  hostname: "Hostname",
};

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source;
}

export function attentionKindLabel(kind: string): string {
  return ATTENTION_LABELS[kind] ?? kind.replaceAll("_", " ");
}

export function activityKindLabel(kind: string): string {
  return ACTIVITY_LABELS[kind] ?? kind.replaceAll("_", " ");
}

export function streamEventKindLabel(kind: string): string {
  return STREAM_EVENT_LABELS[kind] ?? kind.replaceAll("_", " ");
}

export function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity] ?? severity;
}

export function findingStatusLabel(status: string): string {
  return FINDING_STATUS_LABELS[status] ?? status.replaceAll("_", " ");
}

export function findingConfidenceLabel(confidence: string): string {
  return FINDING_CONFIDENCE_LABELS[confidence] ?? confidence;
}

export function feedbackClassificationLabel(classification: string): string {
  return (
    FEEDBACK_CLASSIFICATION_LABELS[classification] ??
    classification.replaceAll("_", " ")
  );
}

export function correlationStatusLabel(status: string): string {
  return CORRELATION_STATUS_LABELS[status] ?? status.replaceAll("_", " ");
}

export function conflictReasonLabel(reason: string): string {
  return CONFLICT_REASON_LABELS[reason] ?? reason.replaceAll("_", " ");
}

export function evidenceKindLabel(kind: string): string {
  return EVIDENCE_KIND_LABELS[kind] ?? kind.replaceAll("_", " ");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export function formatConfidenceScore(
  value: string | number | null | undefined,
): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString(undefined, {
    style: "percent",
    maximumFractionDigits: 0,
  });
}

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";

  const diffSec = Math.round((then - Date.now()) / 1000);
  const abs = Math.abs(diffSec);

  if (abs < 60) return relativeFmt.format(diffSec, "second");
  const diffMin = Math.round(diffSec / 60);
  if (Math.abs(diffMin) < 60) return relativeFmt.format(diffMin, "minute");
  const diffHr = Math.round(diffMin / 60);
  if (Math.abs(diffHr) < 48) return relativeFmt.format(diffHr, "hour");
  const diffDay = Math.round(diffHr / 24);
  return relativeFmt.format(diffDay, "day");
}

export function deviceDisplayName(device: {
  display_name?: string | null;
  id: string;
}): string {
  const name = device.display_name?.trim();
  if (name) return name;
  return `Device ${device.id.slice(0, 8)}`;
}

const PERSON_ROLE_LABELS: Record<string, string> = {
  parent: "Parent",
  child: "Child",
  other: "Other",
};

const IDENTIFIER_KIND_LABELS: Record<string, string> = {
  mac: "MAC",
  unifi_client_id: "UniFi client",
  hostname: "Hostname",
  pihole_client: "Pi-hole client",
  ip: "IP",
};

export function personRoleLabel(role: string): string {
  return PERSON_ROLE_LABELS[role] ?? role;
}

export function identifierKindLabel(kind: string): string {
  return IDENTIFIER_KIND_LABELS[kind] ?? kind.replaceAll("_", " ");
}

export function formatMetricLabel(metric: string): string {
  return metric.replaceAll("_", " ");
}

export function formatCompactNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1000) {
    return new Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  }
  return Number.isInteger(value)
    ? String(value)
    : value.toLocaleString("en", { maximumFractionDigits: 1 });
}
