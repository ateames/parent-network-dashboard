"""PostgreSQL-backed domain enums."""

from __future__ import annotations

from enum import StrEnum


class IngestSource(StrEnum):
    PIHOLE_API = "pihole_api"
    UNIFI_API = "unifi_api"
    UNIFI_SYSLOG = "unifi_syslog"


class IngestBatchStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class IdentifierKind(StrEnum):
    MAC = "mac"
    UNIFI_CLIENT_ID = "unifi_client_id"
    HOSTNAME = "hostname"
    PIHOLE_CLIENT = "pihole_client"
    IP = "ip"


class PersonRole(StrEnum):
    PARENT = "parent"
    CHILD = "child"
    OTHER = "other"


class SourceHealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class DnsQueryStatus(StrEnum):
    """Normalized DNS outcome — never implies content was viewed."""

    ALLOWED = "allowed"
    BLOCKED = "blocked"
    CACHED = "cached"


class CorrelationStatus(StrEnum):
    """Outcome of time-aware DNS → device correlation."""

    ATTRIBUTED = "attributed"
    AMBIGUOUS = "ambiguous"
    UNATTRIBUTED = "unattributed"


class FindingSeverity(StrEnum):
    """Parent-facing severity for explainable findings."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingStatus(StrEnum):
    """Lifecycle of a persisted finding."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class FindingConfidence(StrEnum):
    """How confident the deterministic rule is in the finding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingFeedbackClassification(StrEnum):
    """Parent classification of a finding; drives status + suppression."""

    EXPECTED = "expected"
    CONCERNING = "concerning"
    INCORRECT = "incorrect"
    IGNORE_ONCE = "ignore_once"
    SUPPRESS_SIMILAR = "suppress_similar"
    NEEDS_INVESTIGATION = "needs_investigation"
    ACKNOWLEDGE = "acknowledge"
    RESOLVE = "resolve"


class StreamEventKind(StrEnum):
    """Meaningful live-stream events (not every DNS request)."""

    NEW_DEVICE_JOINED = "new_device_joined"
    UNKNOWN_DEVICE_ONLINE = "unknown_device_online"
    BLOCKED_QUERY_BURST = "blocked_query_burst"
    DNS_VOLUME_INCREASE = "dns_volume_increase"
    ACTIVITY_OUTSIDE_EXPECTED_HOURS = "activity_outside_expected_hours"
    NEW_DOMAIN_BURST = "new_domain_burst"
    CONNECTION_FLAPPING = "connection_flapping"
    UNIFI_SECURITY_EVENT = "unifi_security_event"
    SOURCE_DATA_LOSS = "source_data_loss"
