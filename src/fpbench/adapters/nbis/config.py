"""The three files this route runs, named absolutely and never guessed.

Four settings, and three of them are paths that must be supplied. There is no
default ``mindtct``, no default ``bozorth3``, and no PATH lookup anywhere in this
package: a bare command name means "whatever this machine happens to have
installed first", which is the precise opposite of what a pinned runtime bundle
is for. A distribution's NBIS package, a stale build in ``/usr/local/bin`` and the
certified build differ in ways nothing downstream would notice
(docs/adr/0048, spec section 17).

The build manifest is the third file rather than a derived detail. Which NBIS
produced a score is decided by the two executables *and* by the record of how
they were built and what NIST's own tests said about them; a bundle holding two
binaries and no manifest is not this route's runtime (docs/adr/0042).

**Existence is checked by the environment, not by the constructor.** A missing
executable is one fault of the run, reported as ``EnvironmentStatus.UNAVAILABLE``
and never raised — that is what the adapter contract requires and what the
conformance suite checks (spec section 48). What the constructor enforces is
*shape*: absolute, distinct, not a symlink, not a directory. A configuration that
is wrong in shape is wrong wherever it is read, and there is nothing to report
about it later.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_non_empty_str,
)
from fpbench.core.errors import ConfigurationError

__all__ = [
    "NbisConfig",
    "KNOWN_KEYS",
    "MINDTCT_ROLE",
    "BOZORTH3_ROLE",
    "BUILD_MANIFEST_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
]

#: The roles this route occupies inside a runtime bundle. Three, because all
#: three decide what a score is: either executable can change it, and the
#: manifest is what says the executables are the certified ones (spec section 11).
MINDTCT_ROLE = "nbis_mindtct_executable"
BOZORTH3_ROLE = "nbis_bozorth3_executable"
BUILD_MANIFEST_ROLE = "nbis_build_manifest"

#: Ordered, because the bundle fingerprint and the receipt render them in order.
RUNTIME_ASSET_ROLES: tuple[str, ...] = (
    MINDTCT_ROLE,
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
)

#: The role a receipt names first. It carries no research meaning — the identity
#: of this route is the whole bundle, and a receipt that named one file as "the"
#: executable would be describing half a pipeline (spec section 11).
PRIMARY_RUNTIME_ASSET_ROLE = MINDTCT_ROLE

KNOWN_KEYS = frozenset(
    {
        "adapter_id",
        "mindtct_executable",
        "bozorth3_executable",
        "build_manifest",
        "research_mode",
    }
)


@dataclass(frozen=True, slots=True)
class NbisConfig:
    """Resolved settings for one NBIS adapter instance."""

    mindtct_executable: Path
    bozorth3_executable: Path
    build_manifest: Path

    #: When set, every comparison re-checks that all three files are still the
    #: ones preflight approved. Off by default, exactly as it is for a
    #: development adapter that is not producing citable results.
    research_mode: bool = False

    def __post_init__(self) -> None:
        resolved: dict[Path, str] = {}
        for name in ("mindtct_executable", "bozorth3_executable", "build_manifest"):
            path = Path(getattr(self, name))
            if not path.is_absolute():
                raise ConfigurationError(
                    f"{name} must be an absolute path; a relative one means "
                    "whatever directory the caller happened to be in, and a bare "
                    "name means whatever this machine's PATH says"
                )
            if path.is_symlink():
                raise ConfigurationError(
                    f"{name} is a symlink; a pinned runtime owns its bytes rather "
                    "than pointing at someone else's"
                )
            if path.exists() and not path.is_file():
                raise ConfigurationError(f"{name} is not a regular file")
            previous = resolved.get(path)
            if previous is not None:
                raise ConfigurationError(
                    f"{previous} and {name} name the same file; this route runs two "
                    "distinct executables and reads one manifest"
                )
            resolved[path] = name
            object.__setattr__(self, name, path)

        # Not ``bool(...)``: the string "false" is true under it, and a run that
        # turned research mode on because somebody quoted a YAML boolean would be
        # a run whose pins nothing enforces.
        if type(self.research_mode) is not bool:
            raise ConfigurationError(
                f"research_mode must be a boolean, got "
                f"{type(self.research_mode).__name__}"
            )

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "NbisConfig":
        """Build from adapter-registry configuration.

        All three paths are required. There is deliberately no default for any of
        them: a configuration that does not say which NBIS it runs is not a
        configuration this route can be attributed to.
        """
        where = "nbis"
        reject_unknown_keys(config, KNOWN_KEYS, where=where)
        return cls(
            mindtct_executable=Path(
                require_yaml_non_empty_str(config, "mindtct_executable", where=where)
            ),
            bozorth3_executable=Path(
                require_yaml_non_empty_str(config, "bozorth3_executable", where=where)
            ),
            build_manifest=Path(
                require_yaml_non_empty_str(config, "build_manifest", where=where)
            ),
            research_mode=require_yaml_bool(
                config, "research_mode", where=where, default=False
            ),
        )

    def runtime_assets(self) -> Mapping[str, Path]:
        """The files whose bytes could change a score, by role."""
        return {
            MINDTCT_ROLE: self.mindtct_executable,
            BOZORTH3_ROLE: self.bozorth3_executable,
            BUILD_MANIFEST_ROLE: self.build_manifest,
        }

    def missing_runtime_assets(self) -> tuple[str, ...]:
        """Which roles are absent, unreadable or not executable, by role name.

        The executable bit is checked with ``os.access`` because that is the
        question the operating system will actually be asked when the subprocess
        starts. On Windows it is always satisfied, which is correct: this route's
        certified target is Linux and the platform check is separate.
        """
        problems: list[str] = []
        for role, path in sorted(self.runtime_assets().items()):
            if path.is_symlink() or not path.is_file():
                problems.append(role)
            elif role != BUILD_MANIFEST_ROLE and not os.access(path, os.X_OK):
                problems.append(role)
        return tuple(problems)
