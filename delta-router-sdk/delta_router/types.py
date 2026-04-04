"""Shared data types for the Delta Router SDK."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RoutingDecision:
    """Routing decision returned alongside query results."""

    engine: str
    engine_display_name: str
    stage: str
    reason: str
    complexity_score: float | None


@dataclass(frozen=True)
class ColumnDescription:
    """Single column description per PEP 249 cursor.description.

    Fields: (name, type_code, display_size, internal_size, precision, scale, null_ok)
    Only `name` and `type_code` are populated; the rest are None per spec allowance.
    """

    name: str
    type_code: str | None = None
    display_size: int | None = None
    internal_size: int | None = None
    precision: int | None = None
    scale: int | None = None
    null_ok: bool | None = None

    def __iter__(self):
        """Allow unpacking as a 7-tuple (PEP 249 compatibility)."""
        return iter(
            (
                self.name,
                self.type_code,
                self.display_size,
                self.internal_size,
                self.precision,
                self.scale,
                self.null_ok,
            )
        )
