"""Severity-first ordering helpers for stream events."""

from __future__ import annotations

from collections.abc import Sequence

from app.models.enums import FindingSeverity
from app.schemas.events import StreamEventOut

SEVERITY_RANK: dict[FindingSeverity, int] = {
    FindingSeverity.HIGH: 3,
    FindingSeverity.MEDIUM: 2,
    FindingSeverity.LOW: 1,
    FindingSeverity.INFO: 0,
}


def severity_rank(severity: FindingSeverity) -> int:
    return SEVERITY_RANK.get(severity, 0)


def sort_stream_events(
    events: Sequence[StreamEventOut],
    *,
    limit: int | None = None,
) -> list[StreamEventOut]:
    """Order by severity (high first), then occurred_at (newest), then id."""
    ordered = sorted(
        events,
        key=lambda e: (
            -severity_rank(e.severity),
            -e.occurred_at.timestamp(),
            str(e.id),
        ),
    )
    if limit is None:
        return ordered
    return ordered[: max(0, limit)]
