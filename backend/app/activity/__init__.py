"""Per-device / per-person activity aggregation and transparent baselines."""

from app.activity.aggregate import (
    AGGREGATE_LOGIC_VERSION,
    ActivitySummary,
    aggregate_dns_records,
    parse_window,
)
from app.activity.baseline import (
    BASELINE_LOGIC_VERSION,
    BaselineResult,
    Deviation,
    compute_baseline,
    detect_deviations,
)

__all__ = [
    "AGGREGATE_LOGIC_VERSION",
    "BASELINE_LOGIC_VERSION",
    "ActivitySummary",
    "BaselineResult",
    "Deviation",
    "aggregate_dns_records",
    "compute_baseline",
    "detect_deviations",
    "parse_window",
]
