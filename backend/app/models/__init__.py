"""SQLAlchemy ORM models for the Parent Network Dashboard schema."""

from app.models.activity import ActivityBaseline
from app.models.base import Base
from app.models.dns import DnsActivity, DnsQuery
from app.models.enums import (
    CorrelationStatus,
    DnsQueryStatus,
    FindingConfidence,
    FindingFeedbackClassification,
    FindingSeverity,
    FindingStatus,
    IdentifierKind,
    IngestBatchStatus,
    IngestSource,
    PersonRole,
    SourceHealthStatus,
    StreamEventKind,
)
from app.models.events import StreamEvent
from app.models.findings import Finding, FindingFeedback, FindingSuppression
from app.models.health import AuditLog, SourceHealth
from app.models.identity import Device, DeviceIdentifier, IpAssignment
from app.models.people import Person, PersonDevice
from app.models.raw import (
    IngestBatch,
    RawPiholeEvent,
    RawUnifiClient,
    RawUnifiEvent,
    RawUnifiSyslog,
)
from app.models.settings import (
    AppThresholds,
    ConnectionSettings,
    ExpectedActivitySchedule,
    WorkerHeartbeat,
)

__all__ = [
    "ActivityBaseline",
    "AppThresholds",
    "AuditLog",
    "Base",
    "ConnectionSettings",
    "CorrelationStatus",
    "Device",
    "DeviceIdentifier",
    "DnsActivity",
    "DnsQuery",
    "DnsQueryStatus",
    "ExpectedActivitySchedule",
    "Finding",
    "FindingConfidence",
    "FindingFeedback",
    "FindingFeedbackClassification",
    "FindingSeverity",
    "FindingStatus",
    "FindingSuppression",
    "IdentifierKind",
    "IngestBatch",
    "IngestBatchStatus",
    "IngestSource",
    "IpAssignment",
    "Person",
    "PersonDevice",
    "PersonRole",
    "RawPiholeEvent",
    "RawUnifiClient",
    "RawUnifiEvent",
    "RawUnifiSyslog",
    "SourceHealth",
    "SourceHealthStatus",
    "StreamEvent",
    "StreamEventKind",
    "WorkerHeartbeat",
]

# Tables expected after Alembic migrations (public / test schema).
EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "ingest_batch",
        "raw_pihole_event",
        "raw_unifi_client",
        "raw_unifi_event",
        "raw_unifi_syslog",
        "dns_query",
        "dns_activity",
        "activity_baseline",
        "finding",
        "finding_feedback",
        "finding_suppression",
        "stream_event",
        "device",
        "device_identifier",
        "ip_assignment",
        "person",
        "person_device",
        "source_health",
        "audit_log",
        "app_thresholds",
        "connection_settings",
        "expected_activity_schedule",
        "worker_heartbeat",
    }
)
