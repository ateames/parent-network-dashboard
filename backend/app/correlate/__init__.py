"""Time-aware DNS → device correlation."""

from app.correlate.engine import (
    LOGIC_VERSION,
    ConflictRecord,
    CorrelationDecision,
    EvidenceMatch,
    combine_confidence,
    correlate_time_range,
    correlate_window,
    decide_attribution,
)

__all__ = [
    "LOGIC_VERSION",
    "ConflictRecord",
    "CorrelationDecision",
    "EvidenceMatch",
    "combine_confidence",
    "correlate_time_range",
    "correlate_window",
    "decide_attribution",
]
