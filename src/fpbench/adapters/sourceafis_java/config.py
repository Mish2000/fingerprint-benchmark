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

**Research mode** is the stage 4B addition. In development the adapter runs the
jar Maven just built, at the path Maven put it; that is convenient and entirely
unsuitable for a run whose results will be cited, because a second ``mvnw
package`` replaces those bytes without changing the path. A research adapter is
therefore pinned to a materialised runtime bundle: an id, a fingerprint, the
jar's exact digest and size, and the source revision that will be stamped into
every result (docs/adr/0017, docs/adr/0018). All of it is mandatory together —
half a pin is not a pin.
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
    "BRIDGE_JAR_ROLE",
    "RESEARCH_MODE_KEYS",
]

EXPECTED_SOURCEAFIS_VERSION = "3.18.1"
EXPECTED_BRIDGE_VERSION = "1"
EXPECTED_BRIDGE_PROTOCOL = "fpbench.sourceafis.bridge.v1"

#: The role this adapter's jar occupies inside a runtime bundle. Declared here
#: rather than in ``core``: which files an adapter needs is the adapter's
#: business, and the bundle store only knows that a role names one file.
BRIDGE_JAR_ROLE = "sourceafis_bridge_jar"

#: The pins a research adapter cannot run without. Named as a group because
#: they are only meaningful as a group.
RESEARCH_MODE_KEYS = (
    "runtime_bundle_id",
    "runtime_bundle_fingerprint",
    "expected_bridge_jar_sha256",
    "expected_bridge_jar_size",
    "fpbench_source_revision",
)

_HEX = frozenset("0123456789abcdef")

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

    # ------------------------------------------------------- research pinning
    runtime_bundle_id: str | None = None
    runtime_bundle_fingerprint: str | None = None

    expected_bridge_jar_sha256: str | None = None
    expected_bridge_jar_size: int | None = None

    #: Stamped into every stored result, so a score can be traced back to the
    #: harness build that produced it without consulting anything else.
    fpbench_source_revision: str | None = None

    research_mode: bool = False

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

        object.__setattr__(self, "research_mode", bool(self.research_mode))
        self._validate_research_pins()

    def _validate_research_pins(self) -> None:
        """Refuse a half-configured research adapter.

        A pin that is present but unenforced is worse than no pin: it makes a
        run look reproducible in its manifest while nothing checks it.
        """
        if self.expected_bridge_jar_sha256 is not None:
            digest = str(self.expected_bridge_jar_sha256).strip().lower()
            if len(digest) != 64 or not set(digest) <= _HEX:
                raise ConfigurationError(
                    "expected_bridge_jar_sha256 must be a 64-character hexadecimal "
                    "digest"
                )
            object.__setattr__(self, "expected_bridge_jar_sha256", digest)
        if self.expected_bridge_jar_size is not None:
            size = int(self.expected_bridge_jar_size)
            if size <= 0:
                raise ConfigurationError("expected_bridge_jar_size must be positive")
            object.__setattr__(self, "expected_bridge_jar_size", size)
        if self.runtime_bundle_fingerprint is not None:
            fingerprint = str(self.runtime_bundle_fingerprint).strip().lower()
            if len(fingerprint) != 64 or not set(fingerprint) <= _HEX:
                raise ConfigurationError(
                    "runtime_bundle_fingerprint must be a 64-character hexadecimal "
                    "digest"
                )
            object.__setattr__(self, "runtime_bundle_fingerprint", fingerprint)

        if not self.research_mode:
            return

        missing = [
            name for name in RESEARCH_MODE_KEYS if getattr(self, name) in (None, "")
        ]
        if missing:
            raise ConfigurationError(
                "research_mode requires the runtime to be pinned completely; "
                f"missing: {missing}"
            )

        revision = str(self.fpbench_source_revision).strip().lower()
        if len(revision) != 40 or not set(revision) <= _HEX:
            raise ConfigurationError(
                "fpbench_source_revision must be a full 40-character commit SHA"
            )
        object.__setattr__(self, "fpbench_source_revision", revision)

        # The jar has to live inside the bundle that claims it. Checking the
        # shape of the path is not proof — the digest check in
        # validate_environment is — but it catches the common mistake of
        # pinning a digest while still launching the build output.
        jar = Path(self.bridge_jar)
        parent = jar.parent
        if parent.name != "assets" or parent.parent.name != self.runtime_bundle_id:
            raise ConfigurationError(
                "a research adapter must run the jar from its runtime bundle "
                f"(runtime/bundles/{self.runtime_bundle_id}/assets/), not from a "
                "build directory"
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
            *RESEARCH_MODE_KEYS,
            "research_mode",
        }
        unknown = sorted(set(config) - known)
        if unknown:
            raise ConfigurationError(
                f"unknown sourceafis_java configuration keys: {unknown}"
            )

        jvm_args = config.get("jvm_args")
        size = config.get("expected_bridge_jar_size")
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
            runtime_bundle_id=_optional_text(config.get("runtime_bundle_id")),
            runtime_bundle_fingerprint=_optional_text(
                config.get("runtime_bundle_fingerprint")
            ),
            expected_bridge_jar_sha256=_optional_text(
                config.get("expected_bridge_jar_sha256")
            ),
            expected_bridge_jar_size=int(size) if size is not None else None,
            fpbench_source_revision=_optional_text(
                config.get("fpbench_source_revision")
            ),
            research_mode=bool(config.get("research_mode", False)),
        )

    def pinned_to(
        self,
        *,
        bridge_jar: Path,
        runtime_bundle_id: str,
        runtime_bundle_fingerprint: str,
        expected_bridge_jar_sha256: str,
        expected_bridge_jar_size: int,
        fpbench_source_revision: str,
    ) -> "SourceAfisJavaConfig":
        """A research copy of this configuration, bound to a materialised bundle.

        Returns a new object; the development configuration it was derived from
        is untouched, so the same process can hold both without either one
        quietly acquiring the other's pins.
        """
        return SourceAfisJavaConfig(
            java_executable=self.java_executable,
            bridge_jar=Path(bridge_jar),
            expected_sourceafis_version=self.expected_sourceafis_version,
            expected_bridge_version=self.expected_bridge_version,
            expected_bridge_protocol=self.expected_bridge_protocol,
            jvm_args=self.jvm_args,
            project_root=self.project_root,
            runtime_bundle_id=runtime_bundle_id,
            runtime_bundle_fingerprint=runtime_bundle_fingerprint,
            expected_bridge_jar_sha256=expected_bridge_jar_sha256,
            expected_bridge_jar_size=int(expected_bridge_jar_size),
            fpbench_source_revision=fpbench_source_revision,
            research_mode=True,
        )

    @property
    def jvm_args_text(self) -> str:
        """A stable rendering for the environment report."""
        return " ".join(self.jvm_args)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _repository_root() -> Path:
    """The repository root, derived from this file's location."""
    return Path(__file__).resolve().parents[4]
