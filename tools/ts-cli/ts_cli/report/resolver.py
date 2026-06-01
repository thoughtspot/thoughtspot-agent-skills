"""ts_cli.report.resolver — parse user-provided source input and resolve to GUID."""
from __future__ import annotations

import enum
import re
from typing import Optional

from ts_cli.client import ThoughtSpotClient

# 36-char UUID with hyphens at canonical positions.
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class InputKind(enum.Enum):
    GUID = "guid"
    ONE_PART_NAME = "one_part"
    TWO_PART_NAME = "two_part"
    THREE_PART_NAME = "three_part"
    FOUR_PART_NAME = "four_part"


def looks_like_guid(s: str) -> bool:
    """True iff s is a canonical 36-char UUID."""
    return bool(_GUID_RE.match(s or ""))


def classify_input(s: str) -> InputKind:
    """Return the InputKind for a user-provided source argument."""
    if looks_like_guid(s):
        return InputKind.GUID
    parts = s.split(".")
    n = len(parts)
    if n == 1:
        return InputKind.ONE_PART_NAME
    if n == 2:
        return InputKind.TWO_PART_NAME
    if n == 3:
        return InputKind.THREE_PART_NAME
    if n == 4:
        return InputKind.FOUR_PART_NAME
    raise ValueError(f"Cannot classify input: {s!r}")
