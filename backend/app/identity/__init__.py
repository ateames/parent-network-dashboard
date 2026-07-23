"""Durable device identity resolution."""

from app.identity.resolver import (
    LOGIC_VERSION,
    STRONG_IDENTIFIER_KINDS,
    ClientObservation,
    normalize_mac,
    observation_from_pihole_client,
    resolve_observation,
    resolve_observations,
)

__all__ = [
    "LOGIC_VERSION",
    "STRONG_IDENTIFIER_KINDS",
    "ClientObservation",
    "normalize_mac",
    "observation_from_pihole_client",
    "resolve_observation",
    "resolve_observations",
]
