"""What the adapter needs in order to reach VeriFinger, and nothing more.

Three roles are pinned into a runtime bundle, and all three are **this
project's own bytes** (spec section 17):

.. code-block:: text

    verifinger_bridge_jar        integrations/verifinger-java/target/...
    verifinger_runtime_manifest  configs/verifinger/verifinger_runtime_manifest_v1.json
    verifinger_runtime_policy    configs/verifinger/stage11b_verifinger_runtime_policy_v1.yaml

The 4.7 GB SDK is not one of them and never will be. It stays in the local
artifact store, outside the workspace and outside Git, and the manifest above is
how a run proves which of its bytes it ran — every DLL, every jar and both model
data files, re-verified against the pinned archive before the run and re-checked
before every comparison (spec sections 16 and 19).

Paths are resolved to absolute at construction and kept out of the descriptor
fingerprint and out of every stored result. Where a DLL lives on one machine says
nothing about the experiment, and a result that embeds it stops being portable
evidence (spec section 39).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from fpbench.core.config_values import (
    reject_unknown_keys,
    require_yaml_bool,
    require_yaml_exact_int,
    require_yaml_non_empty_str,
)
from fpbench.core.errors import ConfigurationError
from fpbench.adapters.verifinger_java import identity

__all__ = [
    "VeriFingerJavaConfig",
    "BRIDGE_JAR_ROLE",
    "RUNTIME_MANIFEST_ROLE",
    "RUNTIME_POLICY_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
    "DEFAULT_BRIDGE_JAR",
    "DEFAULT_RUNTIME_MANIFEST",
    "DEFAULT_RUNTIME_POLICY",
    "DEFAULT_JVM_ARGS",
    "INSTALLATION_ENV_VAR",
    "RESEARCH_MODE_KEYS",
    "resolve_installation",
]

BRIDGE_JAR_ROLE = "verifinger_bridge_jar"
RUNTIME_MANIFEST_ROLE = "verifinger_runtime_manifest"
RUNTIME_POLICY_ROLE = "verifinger_runtime_policy"

#: Sorted, because the bundle fingerprint is computed over the role set and a
#: reordering here must not look like a different runtime.
RUNTIME_ASSET_ROLES: tuple[str, ...] = (
    BRIDGE_JAR_ROLE,
    RUNTIME_MANIFEST_ROLE,
    RUNTIME_POLICY_ROLE,
)

PRIMARY_RUNTIME_ASSET_ROLE = BRIDGE_JAR_ROLE

DEFAULT_BRIDGE_JAR = Path(
    "integrations/verifinger-java/target/fpbench-verifinger-bridge.jar"
)
DEFAULT_RUNTIME_MANIFEST = Path(
    "configs/verifinger/verifinger_runtime_manifest_v1.json"
)
DEFAULT_RUNTIME_POLICY = Path(
    "configs/verifinger/stage11b_verifinger_runtime_policy_v1.yaml"
)

#: Pinned so two machines run the same JVM configuration, and headless because
#: nothing on this route has a display. The same set the SourceAFIS bridge uses,
#: minus its image-decoding concerns, because VeriFinger decodes natively.
DEFAULT_JVM_ARGS: tuple[str, ...] = (
    "-Djava.awt.headless=true",
    "-Duser.language=en",
    "-Duser.country=US",
    "-Duser.timezone=UTC",
    "-Xms64m",
    "-Xmx2g",
)

#: How an operator names the prepared SDK installation. An explicit path, then
#: this variable, then the default artifact-store location — and nothing else.
#: There is deliberately no search of a parent directory: a second installation
#: appearing on a machine must not silently change which engine 6,000 results
#: are attributed to.
INSTALLATION_ENV_VAR = "FPBENCH_VERIFINGER_INSTALLATION"

#: The pins a research adapter cannot run without. Named as a group because they
#: are only meaningful as a group; half a pin is not a pin.
RESEARCH_MODE_KEYS = (
    "runtime_bundle_id",
    "runtime_bundle_fingerprint",
    "expected_bridge_jar_sha256",
    "expected_bridge_jar_size",
    "expected_runtime_manifest_fingerprint",
    "fpbench_source_revision",
)

_HEX = frozenset("0123456789abcdef")


#: What ``installation`` resolves to when nobody has said. Not a path: a path
#: this adapter invented would be a path nobody chose, and the environment report
#: would then blame a directory rather than the missing instruction.
UNRESOLVED_INSTALLATION = Path("<unset>")


def resolve_installation(override: object | None = None) -> Path:
    """Which prepared installation to run against, said out loud rather than found.

    An explicit path, then ``FPBENCH_VERIFINGER_INSTALLATION``, and then nothing.
    There is deliberately no search and no default location: an adapter does not
    know where a third-party artifact store lives — that is the experiment
    layer's business, and it passes the path in — and a second installation
    appearing on a machine must not silently change which engine 6,000 results
    are attributed to.
    """
    if override is not None:
        return Path(str(override)).expanduser().resolve()
    from_environment = os.environ.get(INSTALLATION_ENV_VAR)
    if from_environment:
        return Path(from_environment).expanduser().resolve()
    return UNRESOLVED_INSTALLATION


@dataclass(frozen=True, slots=True)
class VeriFingerJavaConfig:
    """Resolved settings for one VeriFinger adapter instance."""

    java_executable: Path = Path("java")
    bridge_jar: Path = DEFAULT_BRIDGE_JAR
    runtime_manifest: Path = DEFAULT_RUNTIME_MANIFEST
    runtime_policy: Path = DEFAULT_RUNTIME_POLICY
    installation: Path | None = None
    jvm_args: tuple[str, ...] = DEFAULT_JVM_ARGS
    project_root: Path | None = None

    expected_bridge_protocol: str = identity.BRIDGE_PROTOCOL
    expected_bridge_version: str = identity.BRIDGE_VERSION
    expected_implementation_version: str = identity.IMPLEMENTATION_VERSION

    # ------------------------------------------------------- research pinning
    runtime_bundle_id: str | None = None
    runtime_bundle_fingerprint: str | None = None
    expected_bridge_jar_sha256: str | None = None
    expected_bridge_jar_size: int | None = None
    expected_runtime_manifest_fingerprint: str | None = None
    fpbench_source_revision: str | None = None

    research_mode: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "jvm_args", tuple(str(arg) for arg in self.jvm_args))

        for name, expected in (
            ("expected_bridge_protocol", identity.BRIDGE_PROTOCOL),
            ("expected_bridge_version", identity.BRIDGE_VERSION),
            ("expected_implementation_version", identity.IMPLEMENTATION_VERSION),
        ):
            value = str(getattr(self, name)).strip()
            if value != expected:
                raise ConfigurationError(
                    f"{name} is fixed at {expected!r} for this adapter version; "
                    f"got {value!r}. Driving a different SDK release is a new "
                    "identity, not a configuration change (docs/adr/0014)"
                )
            object.__setattr__(self, name, value)

        root = Path(self.project_root) if self.project_root else _repository_root()
        object.__setattr__(self, "project_root", root)
        for name in ("bridge_jar", "runtime_manifest", "runtime_policy"):
            value = Path(getattr(self, name))
            object.__setattr__(
                self, name, value if value.is_absolute() else (root / value).resolve()
            )
        object.__setattr__(
            self, "installation", resolve_installation(self.installation)
        )

        # Not ``bool(...)``: the string "false" is true under it, and a run that
        # turned research mode on because somebody quoted a YAML boolean would
        # be a run whose pins nothing enforces.
        if type(self.research_mode) is not bool:
            raise ConfigurationError(
                f"research_mode must be a boolean, got {type(self.research_mode).__name__}"
            )
        self._validate_research_pins()

    def _validate_research_pins(self) -> None:
        for name in (
            "expected_bridge_jar_sha256",
            "runtime_bundle_fingerprint",
            "expected_runtime_manifest_fingerprint",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            digest = str(value).strip().lower()
            if len(digest) != 64 or not set(digest) <= _HEX:
                raise ConfigurationError(
                    f"{name} must be a 64-character hexadecimal digest"
                )
            object.__setattr__(self, name, digest)
        if self.expected_bridge_jar_size is not None:
            # Exact, not ``int(...)``: a size that arrived as "16815" or 16815.0
            # came from a file somebody edited by hand, and rounding it into
            # place would hide that.
            if type(self.expected_bridge_jar_size) is not int:
                raise ConfigurationError(
                    "expected_bridge_jar_size must be an exact integer, got "
                    f"{type(self.expected_bridge_jar_size).__name__}"
                )
            if self.expected_bridge_jar_size <= 0:
                raise ConfigurationError("expected_bridge_jar_size must be positive")

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
        # ``validate_environment`` is — but it catches the common mistake of
        # pinning a digest while still launching the build output.
        parent = Path(self.bridge_jar).parent
        if parent.name != "assets" or parent.parent.name != self.runtime_bundle_id:
            raise ConfigurationError(
                "a research adapter must run the bridge jar from its runtime "
                f"bundle (runtime/bundles/{self.runtime_bundle_id}/assets/), not "
                "from a build directory"
            )

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any]) -> "VeriFingerJavaConfig":
        """Build from adapter-registry configuration, refusing unknown keys."""
        known = {
            "java_executable",
            "bridge_jar",
            "runtime_manifest",
            "runtime_policy",
            "installation",
            "jvm_args",
            "project_root",
            "adapter_id",
            "expected_bridge_protocol",
            "expected_bridge_version",
            "expected_implementation_version",
            *RESEARCH_MODE_KEYS,
            "research_mode",
        }
        reject_unknown_keys(config, known, where="verifinger_java")
        where = "verifinger_java"
        size = config.get("expected_bridge_jar_size")
        return cls(
            java_executable=Path(
                require_yaml_non_empty_str(
                    config, "java_executable", where=where, default="java"
                )
            ),
            bridge_jar=Path(
                require_yaml_non_empty_str(
                    config, "bridge_jar", where=where, default=str(DEFAULT_BRIDGE_JAR)
                )
            ),
            runtime_manifest=Path(
                require_yaml_non_empty_str(
                    config,
                    "runtime_manifest",
                    where=where,
                    default=str(DEFAULT_RUNTIME_MANIFEST),
                )
            ),
            runtime_policy=Path(
                require_yaml_non_empty_str(
                    config,
                    "runtime_policy",
                    where=where,
                    default=str(DEFAULT_RUNTIME_POLICY),
                )
            ),
            installation=(
                Path(require_yaml_non_empty_str(config, "installation", where=where))
                if config.get("installation") is not None
                else None
            ),
            jvm_args=_jvm_args(config),
            project_root=(
                Path(require_yaml_non_empty_str(config, "project_root", where=where))
                if config.get("project_root") is not None
                else None
            ),
            expected_bridge_protocol=require_yaml_non_empty_str(
                config,
                "expected_bridge_protocol",
                where=where,
                default=identity.BRIDGE_PROTOCOL,
            ),
            expected_bridge_version=require_yaml_non_empty_str(
                config,
                "expected_bridge_version",
                where=where,
                default=identity.BRIDGE_VERSION,
            ),
            expected_implementation_version=require_yaml_non_empty_str(
                config,
                "expected_implementation_version",
                where=where,
                default=identity.IMPLEMENTATION_VERSION,
            ),
            runtime_bundle_id=_optional_text(config, "runtime_bundle_id"),
            runtime_bundle_fingerprint=_optional_text(
                config, "runtime_bundle_fingerprint"
            ),
            expected_bridge_jar_sha256=_optional_text(
                config, "expected_bridge_jar_sha256"
            ),
            expected_bridge_jar_size=(
                require_yaml_exact_int(
                    config, "expected_bridge_jar_size", where=where, minimum=1
                )
                if size is not None
                else None
            ),
            expected_runtime_manifest_fingerprint=_optional_text(
                config, "expected_runtime_manifest_fingerprint"
            ),
            fpbench_source_revision=_optional_text(config, "fpbench_source_revision"),
            research_mode=require_yaml_bool(
                config, "research_mode", where=where, default=False
            ),
        )

    def pinned_to(
        self,
        *,
        bridge_jar: Path,
        runtime_manifest: Path,
        runtime_policy: Path,
        runtime_bundle_id: str,
        runtime_bundle_fingerprint: str,
        expected_bridge_jar_sha256: str,
        expected_bridge_jar_size: int,
        expected_runtime_manifest_fingerprint: str,
        fpbench_source_revision: str,
    ) -> "VeriFingerJavaConfig":
        """A research copy of this configuration, bound to a materialised bundle.

        Returns a new object; the development configuration it was derived from
        is untouched, so one process can hold both without either one quietly
        acquiring the other's pins.
        """
        return VeriFingerJavaConfig(
            java_executable=self.java_executable,
            bridge_jar=Path(bridge_jar),
            runtime_manifest=Path(runtime_manifest),
            runtime_policy=Path(runtime_policy),
            installation=self.installation,
            jvm_args=self.jvm_args,
            project_root=self.project_root,
            expected_bridge_protocol=self.expected_bridge_protocol,
            expected_bridge_version=self.expected_bridge_version,
            expected_implementation_version=self.expected_implementation_version,
            runtime_bundle_id=runtime_bundle_id,
            runtime_bundle_fingerprint=runtime_bundle_fingerprint,
            expected_bridge_jar_sha256=expected_bridge_jar_sha256,
            expected_bridge_jar_size=expected_bridge_jar_size,
            expected_runtime_manifest_fingerprint=(
                expected_runtime_manifest_fingerprint
            ),
            fpbench_source_revision=fpbench_source_revision,
            research_mode=True,
        )

    def runtime_assets(self) -> Mapping[str, Path]:
        """The three files a run pins, by role."""
        return {
            BRIDGE_JAR_ROLE: Path(self.bridge_jar),
            RUNTIME_MANIFEST_ROLE: Path(self.runtime_manifest),
            RUNTIME_POLICY_ROLE: Path(self.runtime_policy),
        }

    @property
    def jvm_args_text(self) -> str:
        """A stable rendering for the environment report."""
        return " ".join(self.jvm_args)


def _jvm_args(config: Mapping[str, Any]) -> tuple[str, ...]:
    """The JVM arguments, or the pinned defaults when the key is absent.

    A present-but-empty list is refused rather than silently replaced: "run the
    JVM with no arguments" and "run it with this project's arguments" are
    different experiments.
    """
    if "jvm_args" not in config:
        return DEFAULT_JVM_ARGS
    value = config["jvm_args"]
    if not isinstance(value, (list, tuple)):
        raise ConfigurationError(
            f"verifinger_java: jvm_args must be a list, got {type(value).__name__}"
        )
    if not value:
        raise ConfigurationError(
            "verifinger_java: jvm_args is present but empty; omit the key to use "
            "the pinned defaults"
        )
    arguments: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigurationError(
                "verifinger_java: every jvm_args entry must be a non-empty "
                f"string, got {type(item).__name__} {item!r}"
            )
        arguments.append(item.strip())
    return tuple(arguments)


def _optional_text(config: Mapping[str, Any], key: str) -> str | None:
    """A research pin that may be absent, but may not be the wrong type."""
    if config.get(key) is None:
        return None
    return require_yaml_non_empty_str(config, key, where="verifinger_java")


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[4]
