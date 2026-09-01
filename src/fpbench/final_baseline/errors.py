"""The one failure vocabulary of final-baseline reporting."""

from __future__ import annotations

__all__ = ["FinalBaselineError"]


class FinalBaselineError(RuntimeError):
    """An input, identity or invariant would make the frozen report mean
    something other than what Stage 21A predeclared."""
