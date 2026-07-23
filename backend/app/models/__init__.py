"""SQLAlchemy ORM models for the Parent Network Dashboard schema."""

from app.models.base import Base
from app.models.enums import (
    IdentifierKind,
    IngestBatchStatus,
    IngestSource,
    PersonRole,
    SourceHealthStatus,
)
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

__all__ = [
    "AuditLog",
    "Base",
    "Device",
    "DeviceIdentifier",
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
]

# Tables expected after the initial Alembic migration (public schema).
EXPECTED_TABLES: frozenset[str] = frozenset(
    {
        "ingest_batch",
        "raw_pihole_event",
        "raw_unifi_client",
        "raw_unifi_event",
        "raw_unifi_syslog",
        "device",
        "device_identifier",
        "ip_assignment",
        "person",
        "person_device",
        "source_health",
        "audit_log",
    }
)
