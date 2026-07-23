"""Parent-readable phrasing helpers with honest DNS language.

DNS shows that a lookup was requested — never that content was viewed.
"""

from __future__ import annotations

import re
import uuid

# Words that imply content consumption rather than a DNS lookup.
_FORBIDDEN_VIEWING_RE = re.compile(
    r"\b(viewed|watched|browsed|read|streamed|played)\b",
    re.IGNORECASE,
)


def subject_label(
    *,
    person_name: str | None = None,
    device_name: str | None = None,
    device_id: uuid.UUID | None = None,
) -> str:
    """Human label for who/what a finding is about — never invent a person."""
    if person_name and person_name.strip():
        return person_name.strip()
    if device_name and device_name.strip():
        return device_name.strip()
    if device_id is not None:
        return f"device {device_id}"
    return "unattributed"


def phrase_dns_lookup(
    domain: str,
    *,
    subject: str | None = None,
    blocked: bool = False,
) -> str:
    """Describe a DNS request without claiming content was viewed."""
    clean = domain.strip() or "an unknown domain"
    who = f" attributed to {subject}" if subject and subject != "unattributed" else ""
    if blocked:
        return f"Blocked DNS lookup for {clean}{who}"
    return f"DNS lookup for {clean}{who}"


def phrase_dns_volume(count: int, *, subject: str) -> str:
    """Describe DNS request volume for a subject."""
    noun = "DNS lookup" if count == 1 else "DNS lookups"
    return f"{count} {noun} attributed to {subject}"


def phrase_blocked_burst(
    *,
    blocked_count: int,
    window_minutes: int,
    subject: str,
) -> str:
    """Describe a burst of blocked DNS lookups (not viewed content)."""
    return (
        f"{blocked_count} blocked DNS lookups attributed to {subject} "
        f"within {window_minutes} minutes"
    )


def assert_honest_dns_language(*texts: str) -> None:
    """Raise ``ValueError`` if any text claims content was viewed/watched."""
    for text in texts:
        match = _FORBIDDEN_VIEWING_RE.search(text)
        if match is not None:
            raise ValueError(
                f"Finding text must not claim content was {match.group(1)!r}: {text!r}"
            )


def contains_viewing_claim(text: str) -> bool:
    """Return True if text uses forbidden viewing verbs."""
    return _FORBIDDEN_VIEWING_RE.search(text) is not None
