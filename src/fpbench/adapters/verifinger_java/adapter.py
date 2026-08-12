"""VeriFinger 2025.2, behind the ordinary adapter contract.

The fourth algorithm, and it enters through exactly the same three methods the
dummy matcher did. Nothing in the runner, the executor, the planner or the
storage layer knows this adapter exists, and there is no ``if algorithm_id ==
"verifinger"`` anywhere outside the registry (docs/adr/0007, spec section 20).

What this adapter does *not* do is the more interesting half.

**It applies no threshold and returns no decision.** The bridge sets the
official sample's ``MatchingThreshold = 48`` so that upstream's own 1:1 route is
reproduced exactly, and then fpbench reads the integer score under both ``OK``
and ``MATCH_NOT_FOUND``. The engine's MATCH/NO-MATCH answer never crosses this
boundary (docs/adr/0003, spec section 10).

**It transforms no score.** ``float(native_int)`` is a serialisation: every
32-bit integer is exactly representable in float64. No normalisation, no
clamping, no calibration, and no FAR computed from the vendor's scale
(spec section 11).

**It preprocesses nothing.** The canonical 500 ppi PNG is handed to the SDK as
it stands. No crop, no resize, no rotation, no enhancement, no ROI selection, no
histogram transform, no external minutiae extraction. What the SDK does inside
itself is the SDK's business (spec section 6).

**It never turns a failure into a zero.** Every path that produces no score
produces a ``RawMatchResult.failed()`` carrying a code, a stage and the engine's
own status (spec section 12).

**It refuses to run on a runtime it has not verified.** Every DLL, every jar and
both model data files are hashed before the run, proved to have come from the
pinned SDK archive, and re-checked cheaply before every single comparison. A
component that changes mid-run raises rather than being recorded, because a
result written after a DLL changed would claim provenance it does not have
(spec sections 16 and 19).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.verifinger_java.bridge_client import (
    BridgeClient,
    BridgeProcessError,
    BridgeUnavailable,
    JavaRuntime,
)
from fpbench.adapters.verifinger_java.bridge_models import BridgeVersionInfo
from fpbench.adapters.verifinger_java.config import VeriFingerJavaConfig
from fpbench.adapters.verifinger_java.failure_mapping import (
    contract_violation,
    map_bridge_failure,
    process_crash,
)
from fpbench.core.enums import EnvironmentStatus
from fpbench.core.errors import RuntimeDriftError
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    PreparedImage,
    RawMatchResult,
)
from fpbench.core.verifinger_errors import (
    VeriFingerBridgeContractViolation,
    VeriFingerRuntimeClosureError,
)
from fpbench.adapters.verifinger_java import identity, runtime as runtime_closure

__all__ = ["VeriFingerJavaAdapter", "ALGORITHM_ID", "ADAPTER_ID", "PIPELINE_METADATA"]

ALGORITHM_ID = identity.ALGORITHM_ID
ADAPTER_ID = identity.ADAPTER_ID
PIPELINE_METADATA: Mapping[str, str] = identity.PIPELINE_METADATA


class VeriFingerJavaAdapter(FingerprintAlgorithmAdapter):
    """Compares two prepared images with VeriFinger 2025.2, one JVM per pair."""

    def __init__(self, config: VeriFingerJavaConfig | None = None) -> None:
        self._config = config or VeriFingerJavaConfig()
        self._client = BridgeClient(self._config)
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name=identity.DISPLAY_NAME,
            adapter_id=ADAPTER_ID,
            adapter_version=identity.ADAPTER_VERSION,
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=identity.IMPLEMENTATION_VERSION,
            score_direction=identity.SCORE_DIRECTION,
            deterministic=True,
            capabilities=(),
            metadata=PIPELINE_METADATA,
        )
        # Resolved once per adapter instance, on first use. A run is thousands of
        # comparisons and re-locating the JVM for each would be pure waste.
        self._resolved: tuple[JavaRuntime, Path, Path, BridgeVersionInfo] | None = None
        self._manifest: runtime_closure.RuntimeManifest | None = None
        self._snapshot: runtime_closure.RuntimeIdentitySnapshot | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "VeriFingerJavaAdapter":
        return cls(VeriFingerJavaConfig.from_mapping(config))

    @property
    def config(self) -> VeriFingerJavaConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    @property
    def research_mode(self) -> bool:
        return self._config.research_mode

    @property
    def runtime_manifest(self) -> runtime_closure.RuntimeManifest | None:
        """The verified closure, once ``validate_environment`` has run."""
        return self._manifest

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Prove, in order, that this machine can produce attributable scores.

        Each step is a place the whole run stops, and stopping here is the point:
        a fault found now is one fault of the run, and the same fault found later
        is six thousand identical failures (spec section 18).

        1. the runtime manifest is this route's closure;
        2. every DLL, jar and model file hashes to what the manifest says;
        3. in research mode, the manifest is the one the run was pinned to;
        4. the bridge jar is present, and in research mode is the pinned bytes;
        5. a Java 17+ toolchain exists;
        6. the bridge answers ``version`` with this protocol;
        7. the engine started and reports 2025.2 modules;
        8. the trial licence granted FingerExtractor and FingerMatcher;
        9. every delivered runtime default is the one Stage 11A read.

        A missing dependency is reported, never raised.
        """
        self._resolved = None
        self._manifest = None
        self._snapshot = None

        try:
            installation = self._client.resolve_installation()
            manifest = runtime_closure.read_runtime_manifest(
                Path(self._config.runtime_manifest)
            )
            if (
                self._config.expected_runtime_manifest_fingerprint is not None
                and manifest.fingerprint
                != self._config.expected_runtime_manifest_fingerprint
            ):
                return self._unavailable(
                    "the runtime manifest hashes to "
                    f"{manifest.fingerprint[:12]}..., but this run is pinned to "
                    f"{str(self._config.expected_runtime_manifest_fingerprint)[:12]}..."
                )
            runtime_closure.verify_installation(installation, manifest)
        except (BridgeUnavailable, VeriFingerRuntimeClosureError) as exc:
            return self._unavailable(str(exc))

        try:
            jar = self._client.resolve_jar()
            jar_digest, jar_size = self._client.file_digest(jar)
        except BridgeUnavailable as exc:
            return self._unavailable(str(exc))

        if self._config.research_mode:
            mismatch = self._pin_mismatch(jar_digest, jar_size)
            if mismatch is not None:
                return self._unavailable(mismatch)

        try:
            java = self._client.resolve_java()
            version = self._client.version(java, jar, installation)
        except BridgeUnavailable as exc:
            return self._unavailable(str(exc))
        except VeriFingerBridgeContractViolation as exc:
            return self._unavailable(
                f"the bridge returned an unusable version response: {exc}"
            )
        except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
            return self._unavailable(
                f"the bridge could not be started: {type(exc).__name__}"
            )

        problem = self._version_problem(version)
        if problem is not None:
            return self._unavailable(problem)

        self._manifest = manifest
        self._snapshot = runtime_closure.snapshot_runtime_identity(
            installation, manifest
        )
        self._resolved = (java, jar, installation, version)

        dependencies = {
            "verifinger.version": identity.IMPLEMENTATION_VERSION,
            "verifinger.vendor": identity.VENDOR,
            "verifinger.runtime_manifest.fingerprint": manifest.fingerprint,
            "verifinger.runtime_components": str(len(manifest.components)),
            "verifinger.sdk_archive.sha256": manifest.sdk_archive_sha256,
            "bridge.protocol": version.bridge_protocol,
            "bridge.version": version.bridge_version,
            "bridge.jar.sha256": jar_digest,
            "bridge.jar.size": str(jar_size),
            "jvm.args": self._config.jvm_args_text,
            "licences": version.licences_requested,
        }
        for name, declared in sorted(version.loaded_modules.items()):
            dependencies[f"module.{name}"] = declared
        if self._config.research_mode:
            dependencies["runtime.bundle.id"] = str(self._config.runtime_bundle_id)
            dependencies["runtime.bundle.fingerprint"] = str(
                self._config.runtime_bundle_fingerprint
            )
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=identity.IMPLEMENTATION_VERSION,
            runtime=self._client.runtime_description(java, version),
            dependencies=dependencies,
        )

    def _version_problem(self, version: BridgeVersionInfo) -> str | None:
        """Why the runtime that answered is not the one this route was qualified on."""
        if version.bridge_protocol != self._config.expected_bridge_protocol:
            return (
                f"bridge protocol is {version.bridge_protocol!r}, expected "
                f"{self._config.expected_bridge_protocol!r}"
            )
        if version.bridge_version != self._config.expected_bridge_version:
            return (
                f"bridge version is {version.bridge_version!r}, expected "
                f"{self._config.expected_bridge_version!r}"
            )
        if not version.licences_obtained:
            return (
                "the SDK refused the FingerExtractor and FingerMatcher licences"
                + (f": {version.licence_detail}" if version.licence_detail else "")
                + ". Activate the trial as the vendor documents it; nothing here "
                "bypasses a licence"
            )
        if not version.runtime_started:
            return (
                "the engine did not start"
                + (f": {version.runtime_detail}" if version.runtime_detail else "")
            )
        if not version.loaded_modules:
            return "the engine reported no loaded native modules"
        expected_modules = {
            name.removesuffix(".dll") for name in runtime_closure.NATIVE_LIBRARY_NAMES
        }
        if set(version.loaded_modules) != expected_modules:
            appeared = sorted(set(version.loaded_modules) - expected_modules)
            missing = sorted(expected_modules - set(version.loaded_modules))
            return (
                "the engine loaded a different set of native modules than this "
                f"route pins: appeared={appeared} missing={missing}"
            )
        wrong = sorted(
            f"{name}={declared}"
            for name, declared in version.loaded_modules.items()
            if not declared.startswith(f"{identity.IMPLEMENTATION_VERSION}.")
        )
        if wrong:
            return (
                f"loaded modules do not report {identity.IMPLEMENTATION_VERSION}: "
                f"{wrong}"
            )
        if version.required_ppi != identity.REQUIRED_EFFECTIVE_PPI:
            return (
                f"the bridge runs at {version.required_ppi} ppi, and this route "
                f"is defined at {identity.REQUIRED_EFFECTIVE_PPI}"
            )
        differences = sorted(
            f"{name}={version.delivered_runtime_defaults.get(name)!r} "
            f"(expected {expected!r})"
            for name, expected in identity.EXPECTED_RUNTIME_DEFAULTS.items()
            if version.delivered_runtime_defaults.get(name) != expected
        )
        if differences:
            # Reported, never corrected. A run that quietly set a delivered
            # default back to the qualified value would be publishing results
            # from a runtime nobody qualified (spec section 8).
            return (
                "the delivered runtime defaults are not the ones Stage 11A read "
                f"from a running engine: {differences}"
            )
        return None

    def _pin_mismatch(self, digest: str, size: int) -> str | None:
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
        """Confirm no pinned component has been replaced since preflight.

        One ``stat`` per file, not a re-hash: this runs before every comparison
        and the full digest pass runs before and after the executor.

        Raises:
            RuntimeDriftError: something changed. Fatal to the run — never a
                comparison failure (spec section 19).
        """
        if self._snapshot is None or self._resolved is None:
            raise RuntimeDriftError(
                "the VeriFinger runtime was never validated; a comparison cannot "
                "be attributed to an unchecked engine"
            )
        installation = self._resolved[2]
        runtime_closure.require_runtime_unchanged(installation, self._snapshot)

    def _unavailable(self, message: str) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.UNAVAILABLE,
            implementation_version=identity.IMPLEMENTATION_VERSION,
            runtime={},
            dependencies={},
            # No absolute path here: an environment report is shown to people and
            # stored alongside results (spec section 39).
            message=message,
        )

    # -------------------------------------------------------------- compare

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        """Run one comparison in its own JVM.

        ``left`` is the reference and ``right`` the candidate, fixed. No
        reversal, no averaging of the two directions, no maximum of them, and no
        sorting of the paths — Stage 11A observed symmetry on vendor fixtures and
        that is an observation, not a licence to reorder (spec section 15).

        Both sides are built independently even when the two paths name the same
        file, which is the SELF case and the reason ``extraction_count`` is
        checked to be two on every stored success (spec section 14).

        Raises:
            RuntimeDriftError: a pinned runtime component is no longer the file
                preflight approved. Deliberately the one thing this method raises
                instead of recording.
        """
        java, jar, installation, version = self._require_resolved()
        self.check_runtime_integrity()

        problem = self._resolution_problem(left, right)
        if problem is not None:
            return self._failed(
                contract_violation(problem, details={"kind": "input_resolution"}),
                left,
                right,
            )

        try:
            result = self._client.compare(
                java=java,
                jar=jar,
                installation=installation,
                request_id=context.job_id,
                left_path=left.local_path,
                left_effective_ppi=left.effective_ppi,
                right_path=right.local_path,
                right_effective_ppi=right.effective_ppi,
                working_directory=context.working_directory,
                timeout_seconds=context.timeout_seconds,
            )
        except BridgeProcessError as exc:
            return self._failed(
                process_crash(exit_code=exc.exit_code, stderr=exc.stderr), left, right
            )
        except VeriFingerBridgeContractViolation as exc:
            return self._failed(contract_violation(str(exc)), left, right)

        if not result.succeeded:
            return self._failed(
                map_bridge_failure(
                    code=result.code or "",
                    message=result.message or "",
                    stage=result.stage,
                    side=result.side,
                    exception_type=result.exception_type,
                    engine_status=result.engine_status,
                ),
                left,
                right,
                timings=result.timings_ms,
                engine_status=result.engine_status,
            )

        return RawMatchResult.success(
            # A serialisation, not a transformation: every Java int is exactly
            # representable in float64 (spec section 11).
            raw_score=float(result.score),
            score_direction=identity.SCORE_DIRECTION,
            artifacts=(),
            timing_components_ms=result.timings_ms,
            metadata=self._result_metadata(left, right, result=result),
        )

    def _resolution_problem(
        self, left: PreparedImage, right: PreparedImage
    ) -> str | None:
        """Both sides must already be the resolution this route runs at.

        A requirement, never a conversion. The canonical set is 500 ppi and an
        image that is not is not from that set (spec sections 6 and 7).
        """
        for label, image in (("left", left), ("right", right)):
            if image.effective_ppi != identity.REQUIRED_EFFECTIVE_PPI:
                return (
                    f"the {label} image is {image.effective_ppi} ppi and this "
                    f"route runs at {identity.REQUIRED_EFFECTIVE_PPI} only; "
                    "nothing here resamples a pixel"
                )
        return None

    def _require_resolved(self) -> tuple[JavaRuntime, Path, Path, BridgeVersionInfo]:
        if self._resolved is None:
            # The runner always validates the environment during preflight, so
            # this is a fallback for direct use rather than the normal path.
            report = self.validate_environment()
            if self._resolved is None:
                raise BridgeUnavailable(
                    report.message or "the VeriFinger bridge is unavailable"
                )
        return self._resolved

    def _failed(
        self,
        failure,
        left: PreparedImage,
        right: PreparedImage,
        *,
        timings: Mapping[str, float] | None = None,
        engine_status: str | None = None,
    ) -> RawMatchResult:
        return RawMatchResult.failed(
            failure=failure,
            score_direction=identity.SCORE_DIRECTION,
            artifacts=(),
            timing_components_ms=timings or {},
            metadata=self._result_metadata(left, right, engine_status=engine_status),
        )

    def _result_metadata(
        self,
        left: PreparedImage,
        right: PreparedImage,
        *,
        result=None,
        engine_status: str | None = None,
    ) -> Mapping[str, str]:
        """What the stored result records about how this outcome was produced.

        Everything a reader would otherwise have to infer, and nothing a reader
        could mistake for an answer: no threshold, no decision, no FAR, no
        ground truth, no other algorithm (spec sections 30 and 31).
        """
        prefix = identity.METADATA_PREFIX
        metadata = {
            f"{prefix}algorithm_id": ALGORITHM_ID,
            f"{prefix}adapter_id": ADAPTER_ID,
            f"{prefix}adapter_version": identity.ADAPTER_VERSION,
            f"{prefix}implementation_version": identity.IMPLEMENTATION_VERSION,
            f"{prefix}vendor": identity.VENDOR,
            f"{prefix}bridge_protocol": self._config.expected_bridge_protocol,
            f"{prefix}bridge_version": self._config.expected_bridge_version,
            f"{prefix}integration_mode": identity.INTEGRATION_MODE,
            f"{prefix}input_mode": PIPELINE_METADATA["input_mode"],
            f"{prefix}left_ppi": str(left.effective_ppi),
            f"{prefix}right_ppi": str(right.effective_ppi),
            f"{prefix}probe_side": "left",
            f"{prefix}extraction_policy": "independent_both_sides",
            f"{prefix}template_cache": "disabled",
            f"{prefix}score_cache": "disabled",
            f"{prefix}matching_speed": identity.MATCHING_SPEED,
            f"{prefix}native_score_type": identity.NATIVE_SCORE_TYPE,
            f"{prefix}score_scale": identity.SCORE_SCALE,
            f"{prefix}score_transformation_by_fpbench": (
                identity.SCORE_TRANSFORMATION_BY_FPBENCH
            ),
        }
        if self._manifest is not None:
            metadata[f"{prefix}runtime_manifest_fingerprint"] = (
                self._manifest.fingerprint
            )
        if result is not None:
            metadata[f"{prefix}engine_status"] = str(result.engine_status)
            metadata[f"{prefix}extraction_count"] = str(result.extraction_count)
            if result.left_image_ppi:
                metadata[f"{prefix}left_image_observed_ppi"] = result.left_image_ppi
            if result.right_image_ppi:
                metadata[f"{prefix}right_image_observed_ppi"] = result.right_image_ppi
        elif engine_status:
            metadata[f"{prefix}engine_status"] = engine_status
        if self._config.research_mode:
            # Identity, not diagnostics. A result found on its own must be able
            # to say which runtime and which harness commit produced it, without
            # consulting the run manifest beside it. Still no path.
            metadata.update(
                {
                    f"{prefix}runtime_bundle_id": str(self._config.runtime_bundle_id),
                    f"{prefix}runtime_bundle_fingerprint": str(
                        self._config.runtime_bundle_fingerprint
                    ),
                    f"{prefix}bridge_jar_sha256": str(
                        self._config.expected_bridge_jar_sha256
                    ),
                    f"{prefix}bridge_jar_size": str(
                        self._config.expected_bridge_jar_size
                    ),
                    f"{prefix}fpbench_source_revision": str(
                        self._config.fpbench_source_revision
                    ),
                }
            )
        return metadata
