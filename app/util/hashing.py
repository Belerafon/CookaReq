"""Utilities for hashing identifiers."""
from __future__ import annotations

from hashlib import sha256


def id_to_hash(identifier: str, length: int = 12) -> str:
    """Return the first ``length`` hex digits of SHA-256 for *identifier*.

    Parameters
    ----------
    identifier:
        Source identifier string.
    length:
        Number of hex characters to return (default 12).
    """
    if length <= 0:
        raise ValueError("length must be positive")
    digest = sha256(identifier.encode("utf-8")).hexdigest()
    return digest[:length]
