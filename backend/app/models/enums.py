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
