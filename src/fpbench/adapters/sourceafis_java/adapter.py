"""SourceAFIS for Java, behind the ordinary adapter contract.

The first real biometric system in the project, and it enters through exactly the
same three methods as the dummy matcher did. Nothing in the runner, the executor,
the planner or the storage layer knows this adapter exists (docs/adr/0007).

The identity it declares names the **whole pipeline**, not just the matcher.
SourceAFIS happens to do its own extraction, so extractor and matcher are the same
implementation — but the fields are separate and both filled in, because the next
algorithm will not be so tidy: "Bozorth3" alone would silently omit MINDTCT, and a
result labelled that way could not be attributed (docs/adr/0014).

What this adapter does *not* do is as important as what it does. It applies no
threshold. SourceAFIS documents a recommended 40, and that number lives in the
documentation until a decision policy — a separate layer, a separate record — asks
for it. The adapter stores a raw score and the direction it runs in, and stops
(docs/adr/0003).

Stage 4B adds one thing: in **research mode** the adapter refuses to run
anything but the exact bytes it was pinned to. The digest is recomputed at
preflight, the file's identity is re-checked before every comparison, and every
stored result names the runtime bundle and the fpbench commit that produced it.
A jar replaced mid-run raises rather than being recorded — a result written
after the executable changed would claim provenance it does not have
(docs/adr/0018).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.sourceafis_java.bridge_client import (
    BridgeClient,
    BridgeProcessError,
    BridgeUnavailable,
    JavaRuntime,
)
from fpbench.adapters.sourceafis_java.bridge_models import (
    BridgeContractViolation,
    BridgeVersionInfo,
)
from fpbench.adapters.sourceafis_java.config import (
    EXPECTED_BRIDGE_PROTOCOL,
    EXPECTED_SOURCEAFIS_VERSION,
    SourceAfisJavaConfig,
)
from fpbench.adapters.sourceafis_java.failure_mapping import (
    contract_violation,
    map_bridge_failure,
    process_crash,
)
from fpbench.adapters.sourceafis_java.runtime_guard import (
    FileIdentity,
    require_unchanged,
    snapshot_file_identity,
)
from fpbench.core.enums import EnvironmentStatus, ScoreDirection
from fpbench.core.errors import RuntimeDriftError
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    PreparedImage,
    RawMatchResult,
)

__all__ = [
    "SourceAfisJavaAdapter",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "PIPELINE_METADATA",
]

ALGORITHM_ID = "sourceafis_java"
ADAPTER_ID = "sourceafis_java_subprocess"

#: Everything about the pipeline that could change a score. All of it reaches
#: ``descriptor_fingerprint``, so bumping SourceAFIS, changing the bridge protocol,
#: switching integration mode, or turning on a template cache each produce a
#: different algorithm identity and therefore a different run.
PIPELINE_METADATA: Mapping[str, str] = {
    "family_id": "sourceafis",
    "pipeline_kind": "end_to_end_image_matcher",
    "extractor_id": "sourceafis_java",
    "extractor_version": EXPECTED_SOURCEAFIS_VERSION,
    "matcher_id": "sourceafis_java",
    "matcher_version": EXPECTED_SOURCEAFIS_VERSION,
    "upstream_artifact": (
        f"com.machinezoo.sourceafis:sourceafis:{EXPECTED_SOURCEAFIS_VERSION}"
    ),
    "implementation_language": "java",
    "integration_mode": "subprocess_per_comparison",
    "bridge_protocol": EXPECTED_BRIDGE_PROTOCOL,
    "input_mode": "encoded_image",
    "dpi_policy": "explicit_effective_ppi",
    "probe_side": "left",
    "template_cache": "disabled",
    "template_persistence": "disabled",
    "seed_usage": "ignored_algorithm_has_no_seed",
}


class SourceAfisJavaAdapter(FingerprintAlgorithmAdapter):
    """Compares two prepared images with SourceAFIS 3.18.1 via a Java subprocess."""

    def __init__(self, config: SourceAfisJavaConfig | None = None) -> None:
        self._config = config or SourceAfisJavaConfig()
        self._client = BridgeClient(self._config)
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="SourceAFIS for Java",
            adapter_id=ADAPTER_ID,
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=EXPECTED_SOURCEAFIS_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            capabilities=(),
            metadata=PIPELINE_METADATA,
        )
        # Resolved once per adapter instance, on first use. A run is thousands of
        # comparisons and re-checking the JVM for each of them would be pure waste.
        self._resolved: tuple[JavaRuntime, Path, BridgeVersionInfo] | None = None
        # Taken during environment validation, compared before every comparison.
        self._jar_identity: FileIdentity | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "SourceAfisJavaAdapter":
        return cls(SourceAfisJavaConfig.from_mapping(config))

    @property
    def config(self) -> SourceAfisJavaConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    @property
    def research_mode(self) -> bool:
        return self._config.research_mode

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Locate Java, locate the jar, and make the bridge state its own version.

        The SourceAFIS version is read from SourceAFIS at runtime rather than
        assumed, so a jar built against a different release is refused here instead
        of producing thousands of results attributed to a version that never ran.

        In research mode the jar's own bytes are checked against the pin *before*
        anything else, so a wrong or replaced runtime is caught without a JVM
        even being started, and the file's identity is recorded for the cheap
        per-comparison drift check (docs/adr/0018).

        A missing dependency is reported, never raised: it is one fault of the run,
        not six thousand identical per-pair failures.
        """
        self._jar_identity = None

        try:
            jar = self._client.resolve_jar()
            digest, size = self._client.jar_digest(jar)
        except BridgeUnavailable as exc:
            return self._unavailable(str(exc))

        if self._config.research_mode:
            mismatch = self._pin_mismatch(jar, digest, size)
            if mismatch is not None:
                return self._unavailable(mismatch)

        # Taken here, against the bytes just hashed, rather than after the JVM
        # check: the snapshot's job is to describe the file whose digest was
        # approved, and a missing JVM says nothing about that file.
        try:
            self._jar_identity = snapshot_file_identity(jar)
        except RuntimeDriftError as exc:  # pragma: no cover - it existed a moment ago
            return self._unavailable(str(exc))

        try:
            java = self._client.resolve_java()
            version = self._client.version(java, jar)
        except BridgeUnavailable as exc:
            return self._unavailable(str(exc))
        except BridgeContractViolation as exc:
            return self._unavailable(f"the bridge returned an unusable version response: {exc}")
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - defensive
            return self._unavailable(
                f"the bridge could not be started: {type(exc).__name__}"
            )

        if version.bridge_protocol != self._config.expected_bridge_protocol:
            return self._unavailable(
                f"bridge protocol is {version.bridge_protocol!r}, expected "
                f"{self._config.expected_bridge_protocol!r}"
            )
        if version.bridge_version != self._config.expected_bridge_version:
            return self._unavailable(
                f"bridge version is {version.bridge_version!r}, expected "
                f"{self._config.expected_bridge_version!r}"
            )
        if version.sourceafis_version != self._config.expected_sourceafis_version:
            return self._unavailable(
                f"SourceAFIS on the classpath is {version.sourceafis_version!r}, "
                f"expected {self._config.expected_sourceafis_version!r}"
            )

        self._resolved = (java, jar, version)
        dependencies = {
            "sourceafis": version.sourceafis_version,
            "bridge.version": version.bridge_version,
            "bridge.protocol": version.bridge_protocol,
            "bridge.jar.sha256": digest,
            "bridge.jar.size": str(size),
            "jvm.args": self._config.jvm_args_text,
        }
        if self._config.research_mode:
            # Part of the environment, and therefore of the run's identity: two
            # runs from two bundles are two runs even when the jars happen to
            # hash the same, because the bundle is what a receipt can be
            # checked against later.
            dependencies["runtime.bundle.id"] = str(self._config.runtime_bundle_id)
            dependencies["runtime.bundle.fingerprint"] = str(
                self._config.runtime_bundle_fingerprint
            )

        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=version.sourceafis_version,
            runtime=self._client.runtime_description(java, version),
            dependencies=dependencies,
        )

    def _pin_mismatch(self, jar: Path, digest: str, size: int) -> str | None:
        """Why the jar on disk is not the one this adapter was pinned to.

        Returns ``None`` when it is. A mismatch is reported as UNAVAILABLE
        rather than raised: it is a fault of the run's setup, and the run must
        not start at all (docs/adr/0018).
        """
        if jar.is_symlink():
            return (
                "the pinned bridge jar is a symlink; a runtime bundle owns its "
                "bytes rather than pointing at someone else's"
            )
        if digest != self._config.expected_bridge_jar_sha256:
            return (
                f"the bridge jar hashes to {digest[:12]}..., but this run is "
                f"pinned to {str(self._config.expected_bridge_jar_sha256)[:12]}..."
            )
        if size != self._config.expected_bridge_jar_size:
            return (
                f"the bridge jar is {size} bytes, but this run is pinned to "
                f"{self._config.expected_bridge_jar_size}"
            )
        return None

    def check_runtime_integrity(self) -> None:
        """Confirm the pinned jar has not been replaced since preflight.

        One ``stat``, not a re-hash: this runs before every comparison and the
        full digest runs before and after the executor. Outside research mode
        there is nothing pinned and nothing to check.

        Raises:
            RuntimeDriftError: the file changed. Fatal to the invocation — never
                a comparison failure (docs/adr/0018).
        """
        if not self._config.research_mode:
            return
        if self._jar_identity is None:
            raise RuntimeDriftError(
                "the SourceAFIS runtime was never validated; a research "
                "comparison cannot be attributed to an unchecked executable"
            )
        require_unchanged(
            self._config.bridge_jar, self._jar_identity, label="SourceAFIS bridge jar"
        )

    def _unavailable(self, message: str) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.UNAVAILABLE,
            implementation_version=self._config.expected_sourceafis_version,
            runtime={},
            dependencies={},
            # No absolute path here: an environment report is shown to people and
            # stored alongside results.
            message=message,
        )

    # -------------------------------------------------------------- compare

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        """Run one comparison through the bridge.

        ``left`` is the probe and ``right`` the candidate, fixed. No reversal, no
        averaging of both directions, no maximum of the two — asymmetry, if it is
        ever worth measuring, is a separate experiment rather than a quiet choice
        made here.

        Each side's resolution comes from ``PreparedImage.effective_ppi``, which for
        SD300C is 2000 even though the PNG header says 5080. SourceAFIS ignores
        embedded DPI and needs to be told, which is exactly why this works
        (docs/adr/0004, docs/adr/0016).

        Raises:
            RuntimeDriftError: in research mode, when the pinned jar is no longer
                the file preflight approved. Deliberately the one thing this
                method raises instead of recording.
        """
        java, jar, version = self._require_resolved()
        self.check_runtime_integrity()

        try:
            result = self._client.compare(
                java=java,
                jar=jar,
                request_id=context.job_id,
                left_path=left.local_path,
                left_dpi=left.effective_ppi,
                right_path=right.local_path,
                right_dpi=right.effective_ppi,
                working_directory=context.working_directory,
                timeout_seconds=context.timeout_seconds,
            )
        except BridgeProcessError as exc:
            return self._failed(
                process_crash(exit_code=exc.exit_code, stderr=exc.stderr), left, right
            )
        except BridgeContractViolation as exc:
            return self._failed(contract_violation(str(exc)), left, right)

        if not result.succeeded:
            return self._failed(
                map_bridge_failure(
                    code=result.code or "",
                    message=result.message or "",
                    side=result.side,
                    stage=result.stage,
                    exception_type=result.exception_type,
                ),
                left,
                right,
                timings=result.timings_ms,
            )

        return RawMatchResult.success(
            raw_score=float(result.score),
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=(),
            timing_components_ms=result.timings_ms,
            metadata=self._result_metadata(left, right, version, result.extraction_count),
        )

    def _require_resolved(self) -> tuple[JavaRuntime, Path, BridgeVersionInfo]:
        if self._resolved is None:
            # The runner always validates the environment during preflight, so this
            # is a fallback for direct use rather than the normal path.
            report = self.validate_environment()
            if self._resolved is None:
                raise BridgeUnavailable(report.message or "the SourceAFIS bridge is unavailable")
        return self._resolved

    def _failed(
        self,
        failure,
        left: PreparedImage,
        right: PreparedImage,
        *,
        timings: Mapping[str, float] | None = None,
    ) -> RawMatchResult:
        return RawMatchResult.failed(
            failure=failure,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=(),
            timing_components_ms=timings or {},
            metadata=self._result_metadata(left, right, None, None),
        )

    def _result_metadata(
        self,
        left: PreparedImage,
        right: PreparedImage,
        version: BridgeVersionInfo | None,
        extraction_count: int | None,
    ) -> Mapping[str, str]:
        """What the stored result records about how this score was produced.

        Includes the two resolutions actually sent, so a reader never has to infer
        them, and the extraction policy, so the SELF stage's independence is a
        recorded fact rather than a claim in a docstring.
        """
        metadata = {
            "sourceafis_version": (
                version.sourceafis_version
                if version
                else self._config.expected_sourceafis_version
            ),
            "bridge_version": self._config.expected_bridge_version,
            "bridge_protocol": self._config.expected_bridge_protocol,
            "integration_mode": PIPELINE_METADATA["integration_mode"],
            "input_mode": PIPELINE_METADATA["input_mode"],
            "dpi_policy": PIPELINE_METADATA["dpi_policy"],
            "left_dpi": str(left.effective_ppi),
            "right_dpi": str(right.effective_ppi),
            "probe_side": "left",
            "extraction_policy": "independent_both_sides",
            "template_cache": "disabled",
        }
        if extraction_count is not None:
            metadata["extraction_count"] = str(extraction_count)
        if self._config.research_mode:
            # Identity, not diagnostics. A result found on its own must be able
            # to say which executable and which harness commit produced it,
            # without consulting the run manifest beside it. Still no path: a
            # digest is portable evidence, a directory is not.
            metadata.update(
                {
                    "runtime_bundle_id": str(self._config.runtime_bundle_id),
                    "runtime_bundle_fingerprint": str(
                        self._config.runtime_bundle_fingerprint
                    ),
                    "bridge_jar_sha256": str(self._config.expected_bridge_jar_sha256),
                    "bridge_jar_size": str(self._config.expected_bridge_jar_size),
                    "fpbench_source_revision": str(
                        self._config.fpbench_source_revision
                    ),
                }
            )
        return metadata
