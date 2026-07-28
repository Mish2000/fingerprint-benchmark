"""Identifier types and the rules for composing them.

Identifiers are opaque strings from the point of view of consumers: nothing
outside the module that mints an id is allowed to parse it. They are readable
by design so that a manifest row, a log line and a result row can be lined up
by eye, but readability is a convenience, not a contract.

The only *enforced* property is the character set, which keeps ids safe to use
as filesystem path components and as parquet partition keys.
"""

from __future__ import annotations

import re
from typing import NewType

__all__ = [
    "ImageId",
    "SubjectId",
    "PairId",
    "CohortId",
    "compose_id",
    "validate_id",
    "InvalidIdentifierError",
]

ImageId = NewType("ImageId", str)
SubjectId = NewType("SubjectId", str)
PairId = NewType("PairId", str)
CohortId = NewType("CohortId", str)

_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class InvalidIdentifierError(ValueError):
    """Raised when an identifier would not be safe to use as a path or key."""


def validate_id(value: str) -> str:
    """Return ``value`` unchanged, or raise if it is not a well-formed id."""
    if not _ID_PATTERN.match(value):
        raise InvalidIdentifierError(
            f"identifier {value!r} must be lowercase alphanumeric segments "
            f"joined by single underscores"
        )
    return value


def compose_id(*segments: str | int) -> str:
    """Join segments into a validated identifier.

    Empty segments are dropped so that optional parts can be passed as ``""``.
    """
    parts = [str(segment).strip().lower() for segment in segments]
    return validate_id("_".join(part for part in parts if part))
