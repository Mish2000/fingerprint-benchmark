"""What the two-stage adapter needs in order to reach its two tools.

Three paths and nothing else: the interpreter, the extractor and the matcher.
All three are resolved to absolute at construction, because a subprocess launched
from a relative path depends on whatever directory the caller happened to be in —
and because :class:`~fpbench.adapters.support.process.ExternalCommand` refuses a
relative executable outright.

Everything is read with the strict YAML helpers, so a configuration that says
``timeout_seconds: "60"`` or ``research_mode: "false"`` is refused rather than
reinterpreted (spec section 47).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_non_empty_str,
)
from fpbench.core.errors import ConfigurationError

__all__ = ["SyntheticTwoStageConfig", "KNOWN_KEYS"]

KNOWN_KEYS = frozenset(
    {"adapter_id", "interpreter", "extractor", "matcher", "research_mode"}
)


@dataclass(frozen=True, slots=True)
class SyntheticTwoStageConfig:
    """Resolved settings for one two-stage adapter instance."""

    extractor: Path
    matcher: Path
    interpreter: Path = Path(sys.executable)

    #: When set, every comparison re-checks that the two tools are still the
    #: files preflight approved. Off by default, exactly as it is for a
    #: development adapter that is not producing citable results.
    research_mode: bool = False

    def __post_init__(self) -> None:
        for name in ("extractor", "matcher", "interpreter"):
            path = Path(getattr(self, name))
            if not path.is_absolute():
                raise ConfigurationError(
                    f"{name} must be an absolute path; a relative one means "
                    "whatever directory the caller happened to be in"
                )
            object.__setattr__(self, name, path)
        if self.extractor == self.matcher:
            raise ConfigurationError(
                "the extractor and the matcher must be two different files; a "
                "route whose stages are one file is a one-stage route"
            )
        if type(self.research_mode) is not bool:
            raise ConfigurationError(
                f"research_mode must be a boolean, got "
                f"{type(self.research_mode).__name__}"
            )

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "SyntheticTwoStageConfig":
        reject_unknown_keys(config, KNOWN_KEYS, where="synthetic_two_stage")
        where = "synthetic_two_stage"
        return cls(
            extractor=Path(require_yaml_non_empty_str(config, "extractor", where=where)),
            matcher=Path(require_yaml_non_empty_str(config, "matcher", where=where)),
            interpreter=Path(
                require_yaml_non_empty_str(
                    config, "interpreter", where=where, default=sys.executable
                )
            ),
            research_mode=require_yaml_bool(
                config, "research_mode", where=where, default=False
            ),
        )

    def runtime_assets(self) -> Mapping[str, Path]:
        """The files whose bytes could change a score, by role.

        The interpreter is deliberately not among them. A real route would pin
        its own binaries; this fixture runs two scripts through whichever Python
        is executing the tests, and pretending otherwise would make the guard
        report drift every time the test environment changed.
        """
        from fpbench.adapters.synthetic_two_stage.adapter import (
            EXTRACTOR_ROLE,
            MATCHER_ROLE,
        )

        return {EXTRACTOR_ROLE: self.extractor, MATCHER_ROLE: self.matcher}
