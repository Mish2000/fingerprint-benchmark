"""The four files this route runs, named absolutely and never guessed.

Same rule as the NBIS route's config, for the same reason: no default
``mindtct``, no PATH lookup, no discovery. Which build produced a score is part
of what the score means.

Three of the four are the *certified NBIS build* — the extractor, the matcher it
was certified beside, and the manifest that says so. BOZORTH3 is required even
though this route never runs it, because ``verify_build_manifest`` checks the
manifest against both executables and a manifest verified against half a build is
half a verification. It is deliberately **not** listed as a runtime asset: what
decides an ``nbis_mindtct_openafis`` score is MINDTCT, the manifest, and the
OpenAFIS bridge.
"""

from __future__ import annotations

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
    "OpenAfisConfig",
    "KNOWN_KEYS",
    "MINDTCT_ROLE",
    "BUILD_MANIFEST_ROLE",
    "OPENAFIS_BRIDGE_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
]

MINDTCT_ROLE = "nbis_mindtct_executable"
BUILD_MANIFEST_ROLE = "nbis_build_manifest"
OPENAFIS_BRIDGE_ROLE = "openafis_match_bridge"

#: Ordered. Three, because all three decide what a score is: the extractor, the
#: record that it is the certified extractor, and the matcher bridge.
RUNTIME_ASSET_ROLES: tuple[str, ...] = (
    MINDTCT_ROLE,
    BUILD_MANIFEST_ROLE,
    OPENAFIS_BRIDGE_ROLE,
)

PRIMARY_RUNTIME_ASSET_ROLE = MINDTCT_ROLE

KNOWN_KEYS = frozenset(
    {
        "adapter_id",
        "mindtct_executable",
        "bozorth3_executable",
        "build_manifest",
        "openafis_bridge",
        "research_mode",
    }
)


def _require_shape(path: Path, label: str) -> Path:
    if not path.is_absolute():
        raise ConfigurationError(f"{label} must be an absolute path, got {path}")
    if path.is_symlink():
        raise ConfigurationError(f"{label} must not be a symlink")
    if path.is_dir():
        raise ConfigurationError(f"{label} must be a file, not a directory")
    return path


@dataclass(frozen=True, slots=True)
class OpenAfisConfig:
    """Resolved settings for one MINDTCT -> OpenAFIS adapter instance."""

    mindtct_executable: Path
    bozorth3_executable: Path
    build_manifest: Path
    openafis_bridge: Path

    #: When set, every comparison re-checks that the runtime assets are still the
    #: ones preflight approved.
    research_mode: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.mindtct_executable, "mindtct_executable"),
            (self.bozorth3_executable, "bozorth3_executable"),
            (self.build_manifest, "build_manifest"),
            (self.openafis_bridge, "openafis_bridge"),
        ):
            _require_shape(Path(value), label)
        paths = {
            self.mindtct_executable,
            self.bozorth3_executable,
            self.build_manifest,
            self.openafis_bridge,
        }
        if len(paths) != 4:
            raise ConfigurationError("the four configured paths must be distinct")

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "OpenAfisConfig":
        where = "openafis adapter config"
        reject_unknown_keys(config, KNOWN_KEYS, where=where)
        return cls(
            mindtct_executable=Path(require_yaml_non_empty_str(config, "mindtct_executable", where=where)),
            bozorth3_executable=Path(require_yaml_non_empty_str(config, "bozorth3_executable", where=where)),
            build_manifest=Path(require_yaml_non_empty_str(config, "build_manifest", where=where)),
            openafis_bridge=Path(require_yaml_non_empty_str(config, "openafis_bridge", where=where)),
            research_mode=require_yaml_bool(config, "research_mode", where=where, default=False),
        )

    def runtime_assets(self) -> Mapping[str, Path]:
        """The three files whose bytes define this route's identity."""
        return {
            MINDTCT_ROLE: self.mindtct_executable,
            BUILD_MANIFEST_ROLE: self.build_manifest,
            OPENAFIS_BRIDGE_ROLE: self.openafis_bridge,
        }

    def missing_runtime_assets(self) -> tuple[str, ...]:
        """Roles whose file is absent. Reported, never raised."""
        missing = [role for role, path in self.runtime_assets().items() if not Path(path).is_file()]
        if not Path(self.bozorth3_executable).is_file():
            missing.append("nbis_bozorth3_executable_for_manifest_verification")
        return tuple(missing)
