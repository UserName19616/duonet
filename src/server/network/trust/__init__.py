# src/server/network/trust/__init__.py
"""Trust система."""

from .manager import TrustManager, get_trust_manager
from .levels import (
    TRUST_LEVEL_UNKNOWN,
    TRUST_LEVEL_QUARANTINE,
    TRUST_LEVEL_TRUSTED,
    TRUST_LEVEL_PRIVILEGED,
    QUARANTINE_DAYS,
    DAILY_CLIENT_LIMIT,
    HOURLY_GOSSIP_LIMIT,
    HOURLY_INCOMING_LIMIT,
)
from .violations import (
    VIOLATION_TYPE_INVALID_SIGNATURE,
    VIOLATION_TYPE_INVALID_FORMAT,
    VIOLATION_TYPE_RATE_LIMIT,
    VIOLATION_TYPE_SPAM,
)
from .blacklist import BlacklistManager
from .voting import TrustVotingSystem

__all__ = [
    "TrustManager",
    "get_trust_manager",
    "TRUST_LEVEL_UNKNOWN",
    "TRUST_LEVEL_QUARANTINE",
    "TRUST_LEVEL_TRUSTED",
    "TRUST_LEVEL_PRIVILEGED",
    "QUARANTINE_DAYS",
    "DAILY_CLIENT_LIMIT",
    "HOURLY_GOSSIP_LIMIT",
    "HOURLY_INCOMING_LIMIT",
    "VIOLATION_TYPE_INVALID_SIGNATURE",
    "VIOLATION_TYPE_INVALID_FORMAT",
    "VIOLATION_TYPE_RATE_LIMIT",
    "VIOLATION_TYPE_SPAM",
    "BlacklistManager",
    "TrustVotingSystem",
]
