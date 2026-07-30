"""What the adapter needs to know to reach SourceAFIS.

Paths are resolved to absolute at construction, because a subprocess launched with
a relative path depends on whatever directory the caller happened to be in. They
are deliberately kept *out* of the descriptor fingerprint and out of stored
results: where a jar lives on one machine says nothing about the experiment, and a
result that embeds it stops being portable evidence.

The expected versions are fixed constants for this adapter version. The public
configuration repeats them for an auditable manifest, but cannot override them:
upgrading SourceAFIS or the bridge protocol must be an explicit code change that
updates the dependency, descriptor, pipeline metadata, regression score,
documentation, and adapter version together (docs/adr/0015).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.errors import ConfigurationError

__all__ = [
    "SourceAfisJavaConfig",
    "DEFAULT_BRIDGE_JAR",
    "DEFAULT_JVM_ARGS",
    "EXPECTED_SOURCEAFIS_VERSION",
    "EXPECTED_BRIDGE_VERSION",
    "EXPECTED_BRIDGE_PROTOCOL",
]

EXPECTED_SOURCEAFIS_VERSION = "3.18.1"
EXPECTED_BRIDGE_VERSION = "1"
EXPECTED_BRIDGE_PROTOCOL = "fpbench.sourceafis.bridge.v1"

#: Where ``mvnw package`` puts the shaded jar. A fixed name, never globbed.
DEFAULT_BRIDGE_JAR = Path("integrations/sourceafis-java/target/fpbench-sourceafis-bridge.jar")

#: Pinned so that two machines run the same JVM configuration. Headless because the
#: bridge decodes images through ImageIO; a fixed locale and timezone because a
#: benchmark should not depend on where it is run.
DEFAULT_JVM_ARGS: tuple[str, ...] = (
    "-Djava.awt.headless=true",
    "-Duser.language=en",
    "-Duser.country=US",
    "-Duser.timezone=UTC",
    "-Xms64m",
    "-Xmx2g",
)


@dataclass(frozen=True, slots=True)
class SourceAfisJavaConfig:
    """Resolved settings for one SourceAFIS adapter instance."""

    java_executable: Path = Path("java")
    bridge_jar: Path = DEFAULT_BRIDGE_JAR
    expected_sourceafis_version: str = EXPECTED_SOURCEAFIS_VERSION
    expected_bridge_version: str = EXPECTED_BRIDGE_VERSION
    expected_bridge_protocol: str = EXPECTED_BRIDGE_PROTOCOL
    jvm_args: tuple[str, ...] = DEFAULT_JVM_ARGS
    project_root: Path | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "jvm_args", tuple(str(arg) for arg in self.jvm_args))
        pinned_expectations = (
            ("expected_sourceafis_version", EXPECTED_SOURCEAFIS_VERSION),
            ("expected_bridge_version", EXPECTED_BRIDGE_VERSION),
            ("expected_bridge_protocol", EXPECTED_BRIDGE_PROTOCOL),
        )
        for name, expected in pinned_expectations:
            value = str(getattr(self, name)).strip()
            if not value:
                raise ConfigurationError(f"{name} must not be empty")
            if value != expected:
                raise ConfigurationError(
                    f"{name} is fixed at {expected!r} for this adapter version; "
                    f"got {value!r}"
                )
            object.__setattr__(self, name, value)

        root = Path(self.project_root) if self.project_root else _repository_root()
        object.__setattr__(self, "project_root", root)
        # A bare command name such as "java" is resolved against PATH at validation
        # time; a path is anchored to the repository so a relative config entry means
        # the same thing wherever it is invoked from.
        jar = Path(self.bridge_jar)
        object.__setattr__(
            self, "bridge_jar", jar if jar.is_absolute() else (root / jar).resolve()
        )

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "SourceAfisJavaConfig":
        """Build from adapter-registry configuration.

        Unknown keys are refused rather than ignored: a typo in a config file must
        surface as an error, not as a setting that silently did nothing.
        """
        known = {
            "java_executable",
            "bridge_jar",
            "expected_sourceafis_version",
            "expected_bridge_version",
            "expected_bridge_protocol",
            "jvm_args",
            "project_root",
            "adapter_id",
        }
        unknown = sorted(set(config) - known)
        if unknown:
            raise ConfigurationError(
                f"unknown sourceafis_java configuration keys: {unknown}"
            )

        jvm_args = config.get("jvm_args")
        return cls(
            java_executable=Path(str(config.get("java_executable", "java"))),
            bridge_jar=Path(str(config.get("bridge_jar", DEFAULT_BRIDGE_JAR))),
            expected_sourceafis_version=str(
                config.get("expected_sourceafis_version", EXPECTED_SOURCEAFIS_VERSION)
            ),
            expected_bridge_version=str(
                config.get("expected_bridge_version", EXPECTED_BRIDGE_VERSION)
            ),
            expected_bridge_protocol=str(
                config.get("expected_bridge_protocol", EXPECTED_BRIDGE_PROTOCOL)
            ),
            jvm_args=tuple(str(a) for a in jvm_args) if jvm_args else DEFAULT_JVM_ARGS,
            project_root=(
                Path(str(config["project_root"])) if config.get("project_root") else None
            ),
        )

    @property
    def jvm_args_text(self) -> str:
        """A stable rendering for the environment report."""
        return " ".join(self.jvm_args)


def _repository_root() -> Path:
    """The repository root, derived from this file's location."""
    return Path(__file__).resolve().parents[4]
