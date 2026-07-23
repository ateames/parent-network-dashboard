"""Versioned, transparent activity baselines — means / percentiles / z-scores only.

No ML. Every stored baseline retains the sample inputs used so parents (and
tests) can see exactly how thresholds were derived.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.activity.aggregate import (
    AGGREGATE_LOGIC_VERSION,
    ActivitySummary,
    SubjectType,
    aggregate_activity,
    parse_window,
)
from app.models.activity import ActivityBaseline

BASELINE_LOGIC_VERSION = "activity_baseline.v1"

DEFAULT_Z_THRESHOLD = 2.0
DEFAULT_PERCENTILE = 95.0
DEFAULT_LOOKBACK_SAMPLES = 14
TYPICAL_ACTIVE_HOUR_MIN_FRACTION = 0.5

MetricName = Literal[
    "dns_query_volume",
    "blocked_query_pct",
    "unique_domain_count",
    "new_domain_count",
    "active_hour_count",
    "upload_bytes",
    "download_bytes",
    "connection_duration_seconds",
]

NUMERIC_METRICS: tuple[str, ...] = (
    "dns_query_volume",
    "blocked_query_pct",
    "unique_domain_count",
    "new_domain_count",
    "active_hour_count",
    "upload_bytes",
    "download_bytes",
    "connection_duration_seconds",
)


@dataclass(frozen=True, slots=True)
class MetricBaseline:
    """Transparent stats for one metric across historical windows."""

    metric: str
    sample_count: int
    mean: float
    stddev: float
    percentile: float
    percentile_value: float
    z_threshold: float
    high_threshold_z: float
    high_threshold_percentile: float
    samples: tuple[float, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "sample_count": self.sample_count,
            "mean": self.mean,
            "stddev": self.stddev,
            "percentile": self.percentile,
            "percentile_value": self.percentile_value,
            "z_threshold": self.z_threshold,
            "high_threshold_z": self.high_threshold_z,
            "high_threshold_percentile": self.high_threshold_percentile,
            "samples": list(self.samples),
        }


@dataclass(frozen=True, slots=True)
class Deviation:
    """One explainable deviation of a live value vs baseline."""

    metric: str
    value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float | None
    threshold_kind: str
    threshold_value: float
    delta_from_mean: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "value": self.value,
            "baseline_mean": self.baseline_mean,
            "baseline_stddev": self.baseline_stddev,
            "z_score": self.z_score,
            "threshold_kind": self.threshold_kind,
            "threshold_value": self.threshold_value,
            "delta_from_mean": self.delta_from_mean,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class BaselineResult:
    """Full baseline for a device or person at one window size."""

    subject_type: SubjectType
    subject_id: uuid.UUID
    window: str
    computed_at: datetime
    sample_count: int
    metrics: dict[str, MetricBaseline]
    typical_active_hours_utc: tuple[int, ...]
    day_of_week_patterns: dict[str, Any]
    logic_version: str = BASELINE_LOGIC_VERSION
    inputs: dict[str, Any] = field(default_factory=dict)

    def as_metrics_dict(self) -> dict[str, Any]:
        return {name: mb.as_dict() for name, mb in self.metrics.items()}


def _mean(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _sample_stddev(values: Sequence[float], mean: float) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


def _percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile on a sorted copy (transparent, no interpolation)."""
    if not values:
        return 0.0
    if pct <= 0:
        return float(min(values))
    if pct >= 100:
        return float(max(values))
    ordered = sorted(values)
    # Nearest-rank: rank = ceil(p/100 * n), 1-indexed.
    rank = math.ceil(pct / 100.0 * len(ordered))
    rank = max(1, min(len(ordered), rank))
    return float(ordered[rank - 1])


def compute_metric_baseline(
    values: Sequence[float],
    *,
    metric: str,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    percentile: float = DEFAULT_PERCENTILE,
) -> MetricBaseline:
    samples = tuple(float(v) for v in values)
    mean = _mean(samples)
    stddev = _sample_stddev(samples, mean)
    p_value = _percentile(samples, percentile)
    high_z = mean + (z_threshold * stddev)
    return MetricBaseline(
        metric=metric,
        sample_count=len(samples),
        mean=round(mean, 6),
        stddev=round(stddev, 6),
        percentile=percentile,
        percentile_value=round(p_value, 6),
        z_threshold=z_threshold,
        high_threshold_z=round(high_z, 6),
        high_threshold_percentile=round(p_value, 6),
        samples=samples,
    )


def typical_active_hours(
    samples: Sequence[Sequence[int]],
    *,
    min_fraction: float = TYPICAL_ACTIVE_HOUR_MIN_FRACTION,
) -> tuple[int, ...]:
    """Hours of day that appear in at least ``min_fraction`` of samples."""
    if not samples:
        return ()
    counts: dict[int, int] = defaultdict(int)
    for hours in samples:
        for hour in set(hours):
            if 0 <= hour <= 23:
                counts[hour] += 1
    threshold = min_fraction * len(samples)
    return tuple(sorted(h for h, c in counts.items() if c >= threshold))


def day_of_week_volume_patterns(
    summaries: Sequence[ActivitySummary],
) -> dict[str, Any]:
    """Mean DNS volume by weekday of each sample's ``window_end`` (UTC)."""
    by_dow: dict[int, list[float]] = defaultdict(list)
    for summary in summaries:
        dow = summary.window_end.astimezone(UTC).weekday()
        by_dow[dow].append(float(summary.dns_query_volume))
    patterns: dict[str, Any] = {}
    weekday_names = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    for dow, name in enumerate(weekday_names):
        values = by_dow.get(dow, [])
        patterns[name] = {
            "weekday": dow,
            "sample_count": len(values),
            "mean_dns_query_volume": round(_mean(values), 6) if values else None,
            "samples": values,
        }
    return {
        "method": "mean dns_query_volume grouped by UTC weekday of window_end",
        "weekdays": patterns,
    }


def compute_baseline(
    summaries: Sequence[ActivitySummary],
    *,
    subject_type: SubjectType,
    subject_id: uuid.UUID,
    window: str,
    computed_at: datetime | None = None,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    percentile: float = DEFAULT_PERCENTILE,
) -> BaselineResult:
    """Compute a transparent baseline from historical activity summaries."""
    if not summaries:
        raise ValueError("At least one ActivitySummary sample is required")

    at = computed_at or datetime.now(UTC)
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)

    metrics: dict[str, MetricBaseline] = {}
    for metric in NUMERIC_METRICS:
        values = [
            summary.metric_values()[metric]
            for summary in summaries
            if metric in summary.metric_values()
        ]
        if not values:
            continue
        metrics[metric] = compute_metric_baseline(
            values,
            metric=metric,
            z_threshold=z_threshold,
            percentile=percentile,
        )

    hour_samples = [list(s.active_hours_utc) for s in summaries]
    typical_hours = typical_active_hours(hour_samples)
    dow = day_of_week_volume_patterns(summaries)

    inputs: dict[str, Any] = {
        "logic_version": BASELINE_LOGIC_VERSION,
        "aggregate_logic_version": AGGREGATE_LOGIC_VERSION,
        "window": window,
        "z_threshold": z_threshold,
        "percentile": percentile,
        "typical_active_hour_min_fraction": TYPICAL_ACTIVE_HOUR_MIN_FRACTION,
        "sample_windows": [
            {
                "window_start": s.window_start.isoformat(),
                "window_end": s.window_end.isoformat(),
                "metrics": s.metric_values(),
                "active_hours_utc": list(s.active_hours_utc),
            }
            for s in summaries
        ],
        "method": (
            "Per-metric sample mean and sample stddev (n-1); "
            f"high threshold = mean + {z_threshold}*stddev; "
            f"also nearest-rank p{percentile:g}. "
            "No machine learning."
        ),
    }

    return BaselineResult(
        subject_type=subject_type,
        subject_id=subject_id,
        window=window,
        computed_at=at,
        sample_count=len(summaries),
        metrics=metrics,
        typical_active_hours_utc=typical_hours,
        day_of_week_patterns=dow,
        logic_version=BASELINE_LOGIC_VERSION,
        inputs=inputs,
    )


def detect_deviations(
    summary: ActivitySummary,
    baseline: BaselineResult,
    *,
    z_threshold: float | None = None,
    use_percentile: bool = True,
) -> list[Deviation]:
    """Flag metrics that exceed z-score and/or percentile high thresholds.

    A deviation is returned when the value is above the chosen threshold(s).
    Reasons name the metric and how far it sits from the mean / threshold.
    """
    deviations: list[Deviation] = []
    live = summary.metric_values()

    for metric, value in live.items():
        mb = baseline.metrics.get(metric)
        if mb is None or mb.sample_count < 1:
            continue
        z_cut = z_threshold if z_threshold is not None else mb.z_threshold
        delta = value - mb.mean
        z_score: float | None
        if mb.stddev > 0:
            z_score = delta / mb.stddev
        else:
            z_score = None

        triggered = False
        threshold_kind = ""
        threshold_value = 0.0

        if z_score is not None and z_score > z_cut:
            triggered = True
            threshold_kind = "z_score"
            threshold_value = z_cut
        elif z_score is None and mb.stddev == 0 and value > mb.mean:
            # Constant baseline: any increase is a deviation (explainable).
            triggered = True
            threshold_kind = "above_constant_mean"
            threshold_value = mb.mean
        elif use_percentile and value > mb.high_threshold_percentile:
            # Percentile path when z-score did not already fire.
            if z_score is None or z_score <= z_cut:
                triggered = True
                threshold_kind = f"percentile_p{mb.percentile:g}"
                threshold_value = mb.high_threshold_percentile

        if not triggered:
            continue

        if threshold_kind == "z_score" and z_score is not None:
            reason = (
                f"{metric}={value:g} is {z_score:.2f} standard deviations above "
                f"the baseline mean {mb.mean:g} "
                f"(threshold z>{z_cut:g}; stddev={mb.stddev:g})."
            )
        elif threshold_kind == "above_constant_mean":
            reason = (
                f"{metric}={value:g} is above the constant baseline mean "
                f"{mb.mean:g} (all {mb.sample_count} samples were identical; "
                f"delta={delta:g})."
            )
        else:
            reason = (
                f"{metric}={value:g} exceeds the baseline "
                f"p{mb.percentile:g} threshold {threshold_value:g} "
                f"(mean={mb.mean:g}, delta_from_mean={delta:g})."
            )

        deviations.append(
            Deviation(
                metric=metric,
                value=float(value),
                baseline_mean=mb.mean,
                baseline_stddev=mb.stddev,
                z_score=None if z_score is None else round(z_score, 4),
                threshold_kind=threshold_kind,
                threshold_value=float(threshold_value),
                delta_from_mean=round(delta, 6),
                reason=reason,
            )
        )

    deviations.sort(key=lambda d: d.metric)
    return deviations


def baseline_to_row(result: BaselineResult) -> ActivityBaseline:
    """Map a computed baseline into a persistable ORM row."""
    return ActivityBaseline(
        logic_version=result.logic_version,
        subject_type=result.subject_type,
        subject_id=result.subject_id,
        window=result.window,
        computed_at=result.computed_at,
        sample_count=result.sample_count,
        metrics=result.as_metrics_dict(),
        typical_active_hours_utc=list(result.typical_active_hours_utc),
        day_of_week_patterns=result.day_of_week_patterns,
        inputs=result.inputs,
    )


def row_to_baseline(row: ActivityBaseline) -> BaselineResult:
    """Rehydrate a stored baseline for deviation checks / API responses."""
    metrics: dict[str, MetricBaseline] = {}
    for name, raw in (row.metrics or {}).items():
        metrics[name] = MetricBaseline(
            metric=str(raw.get("metric", name)),
            sample_count=int(raw.get("sample_count", 0)),
            mean=float(raw.get("mean", 0.0)),
            stddev=float(raw.get("stddev", 0.0)),
            percentile=float(raw.get("percentile", DEFAULT_PERCENTILE)),
            percentile_value=float(raw.get("percentile_value", 0.0)),
            z_threshold=float(raw.get("z_threshold", DEFAULT_Z_THRESHOLD)),
            high_threshold_z=float(raw.get("high_threshold_z", 0.0)),
            high_threshold_percentile=float(raw.get("high_threshold_percentile", 0.0)),
            samples=tuple(float(v) for v in (raw.get("samples") or [])),
        )
    subject_type: SubjectType = "person" if row.subject_type == "person" else "device"
    return BaselineResult(
        subject_type=subject_type,
        subject_id=row.subject_id,
        window=row.window,
        computed_at=row.computed_at,
        sample_count=row.sample_count,
        metrics=metrics,
        typical_active_hours_utc=tuple(int(h) for h in row.typical_active_hours_utc),
        day_of_week_patterns=dict(row.day_of_week_patterns or {}),
        logic_version=row.logic_version,
        inputs=dict(row.inputs or {}),
    )


async def collect_historical_summaries(
    session: AsyncSession,
    *,
    subject_type: SubjectType,
    subject_id: uuid.UUID,
    window: str,
    sample_count: int = DEFAULT_LOOKBACK_SAMPLES,
    now: datetime | None = None,
) -> list[ActivitySummary]:
    """Build non-overlapping historical window summaries ending at ``now``."""
    delta = parse_window(window)
    end = now or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)

    device_id = subject_id if subject_type == "device" else None
    person_id = subject_id if subject_type == "person" else None

    summaries: list[ActivitySummary] = []
    cursor_end = end
    for _ in range(sample_count):
        summary = await aggregate_activity(
            session,
            window=window,
            device_id=device_id,
            person_id=person_id,
            now=cursor_end,
        )
        summaries.append(summary)
        cursor_end = cursor_end - delta
    # Oldest first for transparent inputs.
    summaries.reverse()
    return summaries


async def compute_and_store_baseline(
    session: AsyncSession,
    *,
    subject_type: SubjectType,
    subject_id: uuid.UUID,
    window: str,
    sample_count: int = DEFAULT_LOOKBACK_SAMPLES,
    now: datetime | None = None,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
    percentile: float = DEFAULT_PERCENTILE,
    persist: bool = True,
) -> BaselineResult:
    """Compute baseline from historical windows and optionally persist it."""
    summaries = await collect_historical_summaries(
        session,
        subject_type=subject_type,
        subject_id=subject_id,
        window=window,
        sample_count=sample_count,
        now=now,
    )
    # Drop empty leading samples with zero DNS and no UniFi — keep at least one.
    non_empty = [
        s
        for s in summaries
        if s.dns_query_volume > 0
        or s.upload_bytes is not None
        or s.download_bytes is not None
    ]
    use_summaries = non_empty or summaries[-1:]

    result = compute_baseline(
        use_summaries,
        subject_type=subject_type,
        subject_id=subject_id,
        window=window,
        computed_at=now,
        z_threshold=z_threshold,
        percentile=percentile,
    )
    if persist:
        row = baseline_to_row(result)
        session.add(row)
        await session.flush()
    return result


async def get_latest_baseline(
    session: AsyncSession,
    *,
    subject_id: uuid.UUID,
    window: str | None = None,
) -> ActivityBaseline | None:
    """Return the newest stored baseline for a subject (optional window filter)."""
    stmt = (
        select(ActivityBaseline)
        .where(ActivityBaseline.subject_id == subject_id)
        .order_by(ActivityBaseline.computed_at.desc())
    )
    if window is not None:
        stmt = stmt.where(ActivityBaseline.window == window)
    result = await session.execute(stmt.limit(1))
    return result.scalars().first()


def rolling_window_ends(
    *,
    window: str,
    sample_count: int,
    now: datetime,
) -> list[datetime]:
    """Helper for tests: expected window end timestamps (newest last)."""
    delta = parse_window(window)
    ends = []
    cursor = now
    for _ in range(sample_count):
        ends.append(cursor)
        cursor = cursor - delta
    ends.reverse()
    return ends
