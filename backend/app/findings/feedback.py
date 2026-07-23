"""Parent feedback → finding status + suppression matching keys."""

from __future__ import annotations

import uuid
from typing import Any

from app.models.enums import FindingFeedbackClassification, FindingStatus

# Classifications that create a durable suppression rule.
SUPPRESSING_CLASSIFICATIONS: frozenset[FindingFeedbackClassification] = frozenset(
    {FindingFeedbackClassification.SUPPRESS_SIMILAR}
)

_STATUS_BY_CLASSIFICATION: dict[FindingFeedbackClassification, FindingStatus] = {
    FindingFeedbackClassification.EXPECTED: FindingStatus.DISMISSED,
    FindingFeedbackClassification.CONCERNING: FindingStatus.ACKNOWLEDGED,
    FindingFeedbackClassification.INCORRECT: FindingStatus.DISMISSED,
    FindingFeedbackClassification.IGNORE_ONCE: FindingStatus.DISMISSED,
    FindingFeedbackClassification.SUPPRESS_SIMILAR: FindingStatus.DISMISSED,
    FindingFeedbackClassification.NEEDS_INVESTIGATION: FindingStatus.ACKNOWLEDGED,
    FindingFeedbackClassification.ACKNOWLEDGE: FindingStatus.ACKNOWLEDGED,
    FindingFeedbackClassification.RESOLVE: FindingStatus.RESOLVED,
}


def status_for_classification(
    classification: FindingFeedbackClassification,
) -> FindingStatus:
    """Map a parent classification to the finding lifecycle status."""
    return _STATUS_BY_CLASSIFICATION[classification]


def normalize_domain(domain: str) -> str:
    return domain.strip().lower().rstrip(".")


def _collect_domains(evidence: dict[str, Any]) -> list[str]:
    domains: list[str] = []
    for key in ("domains", "new_domains"):
        raw = evidence.get(key)
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, str) and item.strip():
                    domains.append(normalize_domain(item))
    samples = evidence.get("sample_lookups")
    if isinstance(samples, list):
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            domain = sample.get("domain")
            if isinstance(domain, str) and domain.strip():
                domains.append(normalize_domain(domain))
    return domains


def _registrable_suffix(domain: str) -> str:
    """Best-effort parent domain (last two labels) for pattern grouping."""
    parts = [p for p in domain.split(".") if p]
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return domain


def domain_pattern_from_evidence(evidence: dict[str, Any] | None) -> str:
    """Derive a domain pattern for suppression matching.

    - no domains → ``*`` (subject + rule only)
    - one domain → exact domain
    - many domains sharing a suffix → ``*.suffix``
    - otherwise → ``*``
    """
    if not evidence:
        return "*"
    domains = sorted(set(_collect_domains(evidence)))
    if not domains:
        return "*"
    if len(domains) == 1:
        return domains[0]
    suffixes = {_registrable_suffix(d) for d in domains}
    if len(suffixes) == 1:
        suffix = next(iter(suffixes))
        return f"*.{suffix}"
    return "*"


def subject_key(
    device_id: uuid.UUID | None,
    person_id: uuid.UUID | None,
) -> str:
    if device_id is not None:
        return f"device:{device_id}"
    if person_id is not None:
        return f"person:{person_id}"
    return "unattributed"


def suppression_matching_key(
    *,
    rule_id: str,
    device_id: uuid.UUID | None,
    person_id: uuid.UUID | None,
    evidence: dict[str, Any] | None,
) -> tuple[str, str]:
    """Return ``(matching_key, domain_pattern)`` for a finding or draft."""
    pattern = domain_pattern_from_evidence(evidence)
    key = "|".join((rule_id, subject_key(device_id, person_id), pattern))
    return key, pattern


def matching_key_for_finding(finding: Any) -> tuple[str, str]:
    """Build a matching key from a Finding ORM row or FindingDraft."""
    return suppression_matching_key(
        rule_id=finding.rule_id,
        device_id=finding.device_id,
        person_id=finding.person_id,
        evidence=dict(finding.evidence or {}),
    )
