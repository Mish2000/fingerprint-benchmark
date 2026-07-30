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
from fpbench.core.enums import EnvironmentStatus, ScoreDirection
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

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "SourceAfisJavaAdapter":
        return cls(SourceAfisJavaConfig.from_mapping(config))

    @property
    def config(self) -> SourceAfisJavaConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Locate Java, locate the jar, and make the bridge state its own version.

        The SourceAFIS version is read from SourceAFIS at runtime rather than
        assumed, so a jar built against a different release is refused here instead
        of producing thousands of results attributed to a version that never ran.

        A missing dependency is reported, never raised: it is one fault of the run,
        not six thousand identical per-pair failures.
        """
        try:
            java = self._client.resolve_java()
            jar = self._client.resolve_jar()
            digest, size = self._client.jar_digest(jar)
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
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=version.sourceafis_version,
            runtime=self._client.runtime_description(java, version),
            dependencies={
                "sourceafis": version.sourceafis_version,
                "bridge.version": version.bridge_version,
                "bridge.protocol": version.bridge_protocol,
                "bridge.jar.sha256": digest,
                "bridge.jar.size": str(size),
                "jvm.args": self._config.jvm_args_text,
            },
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
        """
        java, jar, version = self._require_resolved()

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
        return metadata
