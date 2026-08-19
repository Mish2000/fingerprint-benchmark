"""The six files this route runs, named absolutely and never guessed.

The same rule the NBIS and OpenAFIS configs follow, for the same reason: no
default ``mindtct``, no PATH lookup for the bridge, no "nearest" or "latest"
MccSdk.dll anywhere on the machine. Which binaries produced a score is part of
what the score means, and a discovery step would let a second copy of the SDK
decide a run's identity without anyone noticing.

Five of the six are runtime assets — their bytes decide the score:

.. code-block:: text

    mindtct           the extractor
    build manifest    the record that it is the certified extractor
    mcc bridge        the process that calls the SDK
    bridge manifest   the record of which source that bridge was built from
    MccSdk.dll        the SDK itself

The bridge manifest is here for the reason the NBIS build manifest is: a compiled
binary's digest is machine-specific and cannot be pinned in the repository, so
the build records it beside the executable and the adapter checks it. Without it
"the MCC bridge digest matches" would have nothing to match against.

BOZORTH3 is required and is deliberately **not** a runtime asset. This route
never runs it, but ``verify_build_manifest`` checks the manifest against both
executables, and a manifest verified against half a build is half a
verification. Requiring it is also what makes "the same MINDTCT as Algorithm 2"
a claim about the same certified build rather than about a similarly named file.
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
    "MccSdkConfig",
    "KNOWN_KEYS",
    "MINDTCT_ROLE",
    "BUILD_MANIFEST_ROLE",
    "MCC_BRIDGE_ROLE",
    "MCC_BRIDGE_MANIFEST_ROLE",
    "MCC_SDK_DLL_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
]

MINDTCT_ROLE = "nbis_mindtct_executable"
BUILD_MANIFEST_ROLE = "nbis_build_manifest"
MCC_BRIDGE_ROLE = "mcc_match_bridge"
MCC_BRIDGE_MANIFEST_ROLE = "mcc_bridge_manifest"
MCC_SDK_DLL_ROLE = "mcc_sdk_dll"

#: Ordered. Five, because all five decide what a score is or record what did.
RUNTIME_ASSET_ROLES: tuple[str, ...] = (
    MINDTCT_ROLE,
    BUILD_MANIFEST_ROLE,
    MCC_BRIDGE_ROLE,
    MCC_BRIDGE_MANIFEST_ROLE,
    MCC_SDK_DLL_ROLE,
)

PRIMARY_RUNTIME_ASSET_ROLE = MINDTCT_ROLE

KNOWN_KEYS = frozenset(
    {
        "adapter_id",
        "mindtct_executable",
        "bozorth3_executable",
        "build_manifest",
        "mcc_bridge",
        "mcc_bridge_manifest",
        "mcc_sdk_dll",
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
class MccSdkConfig:
    """Resolved settings for one MINDTCT -> MCC SDK adapter instance."""

    mindtct_executable: Path
    bozorth3_executable: Path
    build_manifest: Path
    mcc_bridge: Path
    mcc_bridge_manifest: Path
    mcc_sdk_dll: Path

    #: When set, every comparison re-checks that the runtime assets are still the
    #: ones preflight approved.
    research_mode: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.mindtct_executable, "mindtct_executable"),
            (self.bozorth3_executable, "bozorth3_executable"),
            (self.build_manifest, "build_manifest"),
            (self.mcc_bridge, "mcc_bridge"),
            (self.mcc_bridge_manifest, "mcc_bridge_manifest"),
            (self.mcc_sdk_dll, "mcc_sdk_dll"),
        ):
            _require_shape(Path(value), label)
        paths = {
            self.mindtct_executable,
            self.bozorth3_executable,
            self.build_manifest,
            self.mcc_bridge,
            self.mcc_bridge_manifest,
            self.mcc_sdk_dll,
        }
        if len(paths) != 6:
            raise ConfigurationError("the six configured paths must be distinct")

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "MccSdkConfig":
        where = "mcc sdk adapter config"
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
            mcc_bridge=Path(
                require_yaml_non_empty_str(config, "mcc_bridge", where=where)
            ),
            mcc_bridge_manifest=Path(
                require_yaml_non_empty_str(config, "mcc_bridge_manifest", where=where)
            ),
            mcc_sdk_dll=Path(
                require_yaml_non_empty_str(config, "mcc_sdk_dll", where=where)
            ),
            research_mode=require_yaml_bool(
                config, "research_mode", where=where, default=False
            ),
        )

    def runtime_assets(self) -> Mapping[str, Path]:
        """The five files whose bytes define this route's identity."""
        return {
            MINDTCT_ROLE: self.mindtct_executable,
            BUILD_MANIFEST_ROLE: self.build_manifest,
            MCC_BRIDGE_ROLE: self.mcc_bridge,
            MCC_BRIDGE_MANIFEST_ROLE: self.mcc_bridge_manifest,
            MCC_SDK_DLL_ROLE: self.mcc_sdk_dll,
        }

    def missing_runtime_assets(self) -> tuple[str, ...]:
        """Roles whose file is absent. Reported, never raised."""
        missing = [
            role for role, path in self.runtime_assets().items() if not Path(path).is_file()
        ]
        if not Path(self.bozorth3_executable).is_file():
            missing.append("nbis_bozorth3_executable_for_manifest_verification")
        return tuple(missing)
