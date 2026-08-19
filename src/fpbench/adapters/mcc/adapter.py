"""MINDTCT into the official MCC SDK, behind the same three methods as everything else.

.. code-block:: text

    left  PreparedImage -> byte-for-byte copy -> mindtct -> left-nbis.xyt
    right PreparedImage -> byte-for-byte copy -> mindtct -> right-nbis.xyt
    each .xyt           -> mechanical translation -> one MCC payload side
    both sides          -> MCC bridge -> CreateMccTemplate x2 -> MatchMccTemplates
                                                              -> raw System.Double

**The identity is the whole route.** ``nbis_mindtct_mcc_sdk_v2``, because the
official SDK ships no image extractor: it takes minutiae. MINDTCT is therefore a
real part of what produces a score here, and naming the algorithm ``mcc`` would
claim an extractor Bologna never wrote. It shares that extractor with Algorithm
2, which is exactly what makes the pair interesting and exactly why the sharing
is stated rather than presented as two independent systems.

**MINDTCT runs the way Algorithm 2 runs it.** ``mindtct <input.png> <root>``, no
``-b``, no ``-m1``, no quality cutoff, no preprocessing, and the canonical 500 ppi
PNG copied byte for byte — against the same certified Linux build, verified
against the same build manifest, answering the same version probe. Gate B proves
the two routes produce byte-identical XYT rather than merely similar minutiae.

**Nothing of Bologna's was modified.** The vendor assembly is loaded exactly as
downloaded, with not one parameter setter called: ``validate_environment`` asks
the bridge what the SDK's optimal parameters are and compares them to the values
Stage 20A recorded, so a changed default is a refusal to start rather than a
quietly different algorithm.

**SELF is two independent extractions and two independent templates.** The same
image on both sides gets two separate MINDTCT invocations writing to two separate
roots, and the bridge builds a template per side regardless. There is no cache,
no reuse and no ``if left is right: return 1`` — an adapter that noticed both
sides were the same file and answered from one extraction would be measuring
itself.

**One bridge process per comparison.** Slower than a persistent worker and much
easier to audit: no state between pairs, no configuration that can leak, every
comparison starting from the SDK's own defaults, and one pair's failure unable to
contaminate the next.

**A score of 0.0 is a success.** Stage 20A established the SDK's documented range
as an inclusive ``[0,1]`` and that it throws rather than returning zero on error.
Zero is an answer about two fingers, and this adapter never turns it into a
failure — nor a failure into it.

**A score outside that range is recorded, not repaired.** NaN, an infinity or a
number off ``[0,1]`` becomes ``MCC_INVALID_SCORE`` carrying the value verbatim.
There is no clamp, no rounding and no normalisation anywhere in this route.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from time import perf_counter_ns
from typing import Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.errors import AdapterError
from fpbench.adapters.mcc.config import MccSdkConfig
from fpbench.adapters.mcc.failure_mapping import (
    STAGE20B_STATUSES,
    STATUS_KEY,
    bridge_failure,
    infrastructure_failure,
    invalid_score_failure,
    invalid_xyt_failure,
    match_refused_failure,
    mcc_runtime_failure,
    mindtct_failure,
    template_refused_failure,
)
from fpbench.adapters.mcc.interop import InteropPathUnreachable, windows_path
from fpbench.adapters.mcc.identity import (
    ADAPTER_ID,
    ADAPTER_VERSION,
    ALGORITHM_ID,
    BRIDGE_PROTOCOL,
    DISPLAY_NAME,
    IMPLEMENTATION_VERSION,
    MATCH_API,
    MCC_INPUT_RESOLUTION,
    MCC_SDK_ASSEMBLY_FULL_NAME,
    MCC_SDK_DLL_SHA256,
    MCC_SDK_VERSION,
    MCC_VARIANT,
    SCORE_MAXIMUM,
    SCORE_MINIMUM,
    SDK_OPTIMAL_PARAMETERS,
    SHARES_EXTRACTOR_WITH,
    TEMPLATE_API,
    UPSTREAM_MODIFIED,
)
from fpbench.adapters.mcc.translation import (
    MccTranslationRefused,
    render_bridge_payload,
    translate_xyt_to_mcc_input,
)
from fpbench.adapters.nbis.adapter import VERSION_PROBES, version_probe
from fpbench.adapters.nbis.build_manifest import (
    EXPECTED_NBIS_VERSION,
    SUPPORTED_TARGETS,
    NbisBuildManifestError,
    host_target,
    read_build_manifest,
    verify_build_manifest,
)
from fpbench.adapters.nbis.failure_mapping import (
    EXTRACTION_STAGE,
    MINDTCT_TOOL,
    is_process_crash,
)
from fpbench.adapters.nbis.png_input import NbisInputRejected, require_gray8_500ppi_png
from fpbench.adapters.nbis.xyt import XytFormatError, read_xyt
from fpbench.adapters.pipeline_metadata import AlgorithmPipelineMetadata
from fpbench.adapters.support.process import (
    ExternalCommand,
    ExternalCommandResult,
    run_external_command,
)
from fpbench.adapters.support.runtime_guard import (
    FileIdentity,
    require_runtime_assets_unchanged,
    snapshot_runtime_assets,
)
from fpbench.adapters.support.workspace import AdapterJobWorkspace
from fpbench.core.enums import (
    EnvironmentStatus,
    FailureCode,
    FailureStage,
    ScoreDirection,
)
from fpbench.core.errors import ResearchPreflightError, RuntimeDriftError
from fpbench.core.execution_models import (
    AlgorithmDescriptor,
    ComparisonContext,
    EnvironmentReport,
    FailureInfo,
    PreparedImage,
    RawMatchResult,
    runtime_description,
)

__all__ = [
    "MccSdkAdapter",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "IMPLEMENTATION_VERSION",
    "PIPELINE_METADATA",
    "RESULT_METADATA",
    "STAGE20B_STATUSES",
    "BRIDGE_OUTPUT_FIELDS",
    "BRIDGE_MANIFEST_SCHEMA",
]

LEFT_INPUT = "left-input.png"
RIGHT_INPUT = "right-input.png"
LEFT_OUTPUT_ROOT = "left-nbis"
RIGHT_OUTPUT_ROOT = "right-nbis"
PAYLOAD_NAME = "mcc-payload.txt"

#: What ``scripts/stage20b_gate_a.py --build`` writes beside the executable.
#: Reading it is how "the MCC bridge digest matches" has something to match.
BRIDGE_MANIFEST_SCHEMA = "stage_20b_mcc_bridge_manifest_v1"

#: The bridge prints one tab-separated line in exactly this shape.
BRIDGE_OUTPUT_FIELDS: tuple[str, ...] = (
    "status",
    "score",
    "template_left_us",
    "template_right_us",
    "match_us",
    "left_minutiae",
    "right_minutiae",
    "detail",
)

#: The bridge is a Windows .NET Framework process, reached from Linux through WSL
#: interop and run directly on Windows. It needs **no** environment of its own in
#: either case: the vendor assembly is loaded from the bridge's own directory
#: rather than off a search path, and ``run_external_command``'s deterministic
#: base plus its Windows floor is enough for the CLR to start. So nothing here
#: passes ``os.environ`` through, and no variable a developer happened to export
#: can reach the SDK.
_BRIDGE_IDENTITY_TIMEOUT_SECONDS = 120.0
_NS_PER_MS = 1_000_000
_READ_CHUNK = 1 << 20

PIPELINE = AlgorithmPipelineMetadata(
    # Deliberately not "nbis" and not "mcc": the family is the composition, and
    # either single name would attribute half the route to the wrong upstream.
    family_id="nbis_mindtct_mcc_sdk_v2",
    pipeline_kind="extract_then_match",
    extractor_id="mindtct",
    extractor_version=EXPECTED_NBIS_VERSION,
    matcher_id="mcc_sdk",
    matcher_version=MCC_SDK_VERSION,
    implementation_language="c_and_csharp",
    integration_mode="subprocess_per_stage",
    input_mode="direct_gray8_png_byte_copy",
    dpi_policy="png_ppi_undefined_nbis_default_500",
    probe_side="left",
    template_cache="disabled",
    template_persistence="disabled",
    seed_usage="ignored_algorithm_has_no_seed",
    extra={
        # The options this route does not pass, and the three translation rules
        # Stage 20A settled from the two upstreams' published conventions. Named
        # so that changing one later is visibly a different identity rather than
        # a quiet edit.
        "mindtct_contrast_boost": "disabled",
        "mindtct_m1": "disabled",
        "mcc_variant": MCC_VARIANT,
        "mcc_parameters": "sdk_optimal_defaults",
        "mcc_parameter_setters_called": "false",
        "mcc_threshold": "none",
        "mcc_score_transform": "none",
        "mcc_score_native_type": "System.Double",
        "mcc_score_range": f"[{SCORE_MINIMUM},{SCORE_MAXIMUM}]",
        "mcc_input_resolution": str(MCC_INPUT_RESOLUTION),
        "mcc_upstream_modified": "false",
        "minutiae_quality_transferred": "no",
        "minutiae_type_transferred": "no",
        "minutiae_filtering": "none",
        "minutiae_ordering": "mindtct_order_preserved",
        "coordinate_scaling": "none",
        "coordinate_origin_change": "y_mcc = image_height - y_xyt",
        "angle_conversion": "direction_mcc = theta_xyt_degrees * pi / 180",
        "input_effective_ppi": "500",
        "shares_extractor_with": SHARES_EXTRACTOR_WITH,
        "sd300_used_for_parameter_selection": "false",
        "sd300_used_for_route_selection": "false",
    },
)
#: The descriptor metadata as a plain mapping, for the validator to compare
#: against without rebuilding the adapter.
PIPELINE_METADATA: Mapping[str, str] = PIPELINE.as_descriptor_metadata()

#: What every stored result records about how this score was produced. Fixed for
#: the identity; the per-comparison keys are added beside it.
RESULT_METADATA: Mapping[str, str] = {
    "pipeline": ALGORITHM_ID,
    "nbis_version": EXPECTED_NBIS_VERSION,
    "mcc_sdk_version": MCC_SDK_VERSION,
    "mcc_variant": MCC_VARIANT,
    "input_format": "png",
    "input_depth": "8",
    "input_transport": "byte_for_byte_copy",
    "effective_ppi": "500",
    "ppi_policy": "nbis_png_default_500",
    "mindtct_mode": "default",
    "mindtct_m1": "disabled",
    "mcc_threshold": "none",
    "mcc_score_transform": "none",
    "mcc_parameter_setters_called": "false",
    "mcc_upstream_modified": "false",
    "minutiae_quality_transferred": "no",
    "minutiae_filtering": "none",
    "coordinate_scaling": "none",
    "sd300_used_for_parameter_selection": "false",
}


class MccCleanupError(AdapterError):
    """A file this comparison wrote is still on disk."""


class _StageFailure(Exception):
    def __init__(self, info: FailureInfo) -> None:
        super().__init__(info.message)
        self.info = info


class _Budget:
    """The comparison's remaining time, shared across its subprocesses."""

    def __init__(self, total_seconds: float) -> None:
        self._total = float(total_seconds)
        self._started = perf_counter_ns()

    def remaining(self) -> float:
        return self._total - (perf_counter_ns() - self._started) / 1_000_000_000


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(_READ_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _as_scalar(text: str) -> object:
    """One identity value, in the type the frozen table holds it as.

    The bridge prints doubles in .NET's 17-digit round-trip form, so ``0.5236…82``
    arrives where the table holds ``0.5236…8``. Both name the same
    ``System.Double``, which is why this parses rather than compares text.
    """
    if text == "null":
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


class MccSdkAdapter(FingerprintAlgorithmAdapter):
    """Compares two prepared 500 ppi greyscale PNGs with MINDTCT and MCC SDK v2.0."""

    def __init__(self, config: MccSdkConfig) -> None:
        self._config = config
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name=DISPLAY_NAME,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=IMPLEMENTATION_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            capabilities=(),
            metadata=PIPELINE_METADATA,
        )
        self._runtime: Mapping[str, FileIdentity] | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "MccSdkAdapter":
        return cls(MccSdkConfig.from_mapping(config))

    @property
    def config(self) -> MccSdkConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Is this the certified NBIS build, and is this Stage 20A's MCC SDK?

        Section 12's list, in order, and every one of them a check against a
        pinned value rather than a search:

        .. code-block:: text

            certified MINDTCT binary exists
            NBIS build manifest matches
            MCC bridge exists
            MccSdk.dll exists and its SHA-256 is Stage 20A's
            Windows interop works and the bridge loads the SDK
            the SDK's optimal parameters are still the recorded ones
            the expected algorithm identity matches

        There is no PATH lookup, no nearest version and no fallback anywhere in
        it. An asset that is absent is ``UNAVAILABLE``; an asset that is present
        and *different* is also ``UNAVAILABLE``, because a run attributed to
        Stage 20A's SDK must have been produced by Stage 20A's SDK.
        """
        self._runtime = None

        host = host_target()
        if host not in SUPPORTED_TARGETS:
            return self._unavailable(
                f"this build of NBIS runs on {sorted(SUPPORTED_TARGETS)} "
                f"and this machine is {host[0]}/{host[1]}"
            )

        missing = self._config.missing_runtime_assets()
        if missing:
            return self._unavailable(f"the pinned runtime is missing: {list(missing)}")

        try:
            manifest = read_build_manifest(self._config.build_manifest)
            verify_build_manifest(
                manifest,
                mindtct=self._config.mindtct_executable,
                bozorth3=self._config.bozorth3_executable,
            )
        except NbisBuildManifestError as exc:
            return self._manifest_problem(str(exc))

        if manifest.target != host:
            return self._unavailable(
                f"the build targets {manifest.target_os}/{manifest.target_architecture} "
                f"and this machine is {host[0]}/{host[1]}"
            )

        observed = version_probe(
            self._config.mindtct_executable, VERSION_PROBES[MINDTCT_TOOL]
        )
        if observed is None:
            return self._unavailable("mindtct could not be run")
        if observed != manifest.mindtct_version_output:
            return self._manifest_problem(
                "mindtct no longer answers its version probe the way the build "
                "manifest recorded"
            )

        digest = _sha256(self._config.mcc_sdk_dll)
        if digest != MCC_SDK_DLL_SHA256:
            return self._unavailable(
                "MccSdk.dll is not the assembly Stage 20A qualified; this route's "
                "identity names that assembly and no other"
            )

        bridge_digest = _sha256(self._config.mcc_bridge)
        problem = self._bridge_build_problem(bridge_digest=bridge_digest, sdk_digest=digest)
        if problem is not None:
            return self._unavailable(problem)

        bridge = self._probe_bridge()
        if bridge is None:
            return self._unavailable(
                "the mcc bridge could not be run; Windows interop is required for "
                "this route"
            )
        problem = self._bridge_disagreement(bridge)
        if problem is not None:
            return self._unavailable(problem)

        try:
            self._runtime = snapshot_runtime_assets(self._config.runtime_assets())
        except RuntimeDriftError as exc:  # pragma: no cover
            return self._unavailable(str(exc))

        summary = manifest.official_test_summary
        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=IMPLEMENTATION_VERSION,
            runtime={
                **dict(runtime_description()),
                "nbis.target_os": manifest.target_os,
                "nbis.target_architecture": manifest.target_architecture,
                "nbis.compiler_id": manifest.compiler_id,
                "mcc.clr_version": bridge.get("clr_version", ""),
                "mcc.process_64bit": bridge.get("process_64bit", ""),
                "mcc.image_runtime_version": bridge.get("image_runtime_version", ""),
            },
            dependencies={
                "nbis.version": manifest.nbis_version,
                "nbis.build_manifest_fingerprint": manifest.manifest_fingerprint,
                "nbis.mindtct.sha256": manifest.mindtct_sha256,
                "nbis.mindtct.size": str(manifest.mindtct_size_bytes),
                "nbis.official_tests.passed": str(summary.passed_tests),
                "mcc.assembly_full_name": bridge.get("assembly_full_name", ""),
                "mcc.sdk_dll_sha256": digest,
                "mcc.bridge_protocol": bridge.get("bridge_protocol", ""),
                "mcc.bridge_version": bridge.get("bridge_version", ""),
                "mcc.bridge_sha256": bridge_digest,
                "mcc.bridge_source_sha256": self._bridge_manifest().get(
                    "bridge_source_sha256", ""
                ),
                "mcc.variant": bridge.get("variant", ""),
                "mcc.parameter_setters_called": bridge.get(
                    "parameter_setters_called", ""
                ),
                "mcc.score_native_type": bridge.get("score_native_type", ""),
                "mcc.score_transform": bridge.get("score_transform", ""),
                "mcc.threshold": bridge.get("threshold", ""),
                "mcc.optimal_parameters_match_stage20a": "true",
            },
        )

    def _bridge_manifest(self) -> Mapping[str, object]:
        """What the build recorded about the bridge sitting beside it."""
        try:
            document = json.loads(
                Path(self._config.mcc_bridge_manifest).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return {}
        return document if isinstance(document, dict) else {}

    def _bridge_build_problem(self, *, bridge_digest: str, sdk_digest: str) -> str | None:
        """Is this the bridge the build recorded, built from the committed source?

        A compiled binary's digest cannot be pinned in the repository — a
        different .NET Framework servicing level produces different bytes from
        identical source — so the build writes it down beside the executable and
        this checks it, exactly as the NBIS build manifest is checked. What *is*
        pinned in the repository is the bridge's source, and the manifest carries
        its digest too, so the chain from committed source to running process is
        closed rather than assumed.
        """
        manifest = self._bridge_manifest()
        if not manifest:
            return (
                "the mcc bridge manifest is absent or unreadable; rebuild the bridge "
                "with scripts/stage20b_gate_a.py --build"
            )
        if manifest.get("schema") != BRIDGE_MANIFEST_SCHEMA:
            return f"the mcc bridge manifest is not a {BRIDGE_MANIFEST_SCHEMA} document"
        if manifest.get("bridge_sha256") != bridge_digest:
            return (
                "the mcc bridge is not the binary its manifest recorded; a run "
                "cannot be attributed to a bridge nobody built"
            )
        if manifest.get("sdk_dll_sha256") != sdk_digest:
            return "the mcc bridge was built against a different MccSdk.dll"
        if not str(manifest.get("bridge_source_sha256", "")):
            return "the mcc bridge manifest does not say which source it was built from"
        # Whether that source digest still matches the *committed* Program.cs is
        # checked where the repository layout is known — the evidence layer. An
        # adapter may not go looking for the working tree it happens to live in.
        return None

    def _probe_bridge(self) -> dict[str, str] | None:
        """Ask the bridge what it is. Returns its key/value report, or None."""
        directory = Path(self._config.mcc_bridge).parent
        result = run_external_command(
            ExternalCommand(
                argv=(str(self._config.mcc_bridge), "identity"),
                working_directory=directory,
                containment_root=directory,
                timeout_seconds=_BRIDGE_IDENTITY_TIMEOUT_SECONDS,
            )
        )
        if result.launch_failed or result.timed_out or result.exit_code != 0:
            return None
        report: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "\t" in line:
                key, value = line.split("\t", 1)
                report[key.strip()] = value.strip()
        return report or None

    def _bridge_disagreement(self, bridge: Mapping[str, str]) -> str | None:
        """Everything about the loaded SDK that must still be Stage 20A's.

        Returns the first disagreement as a sentence, or ``None``. Checked here
        rather than trusted because the whole methodological claim of this route
        is "the official matcher, unmodified, at its own defaults" — and that is
        a statement about the assembly this process just loaded.
        """
        expected = {
            "bridge_protocol": BRIDGE_PROTOCOL,
            "assembly_full_name": MCC_SDK_ASSEMBLY_FULL_NAME,
            "assembly_version": MCC_SDK_VERSION,
            "template_api": TEMPLATE_API,
            "match_api": MATCH_API,
            "variant": MCC_VARIANT,
            "parameter_setters_called": "false",
            "score_native_type": "System.Double",
            "score_transform": "NONE",
            "threshold": "NONE",
            "template_cache": "disabled",
        }
        for key, value in expected.items():
            observed = bridge.get(key)
            if observed != value:
                return (
                    f"the mcc bridge reports {key}={observed!r}; this route is "
                    f"defined against {value!r}"
                )

        for prefix, parameters in SDK_OPTIMAL_PARAMETERS.items():
            for name, value in parameters.items():
                observed = bridge.get(f"{prefix}.{name}")
                if observed is None:
                    return f"the mcc bridge did not report {prefix}.{name}"
                if _as_scalar(observed) != value:
                    return (
                        f"the mcc sdk reports {prefix}.{name}={observed!r} where "
                        f"Stage 20A recorded {value!r}; this route runs the SDK's "
                        "own optimal defaults and nothing else"
                    )
        return None

    def _unavailable(self, reason: str) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.UNAVAILABLE,
            implementation_version=IMPLEMENTATION_VERSION,
            message=reason,
        )

    def _manifest_problem(self, reason: str) -> EnvironmentReport:
        if self._config.research_mode:
            raise ResearchPreflightError(
                f"a research run cannot be attributed to an uncertified NBIS build: {reason}"
            )
        return self._unavailable(reason)

    def check_runtime_integrity(self) -> None:
        if not self._config.research_mode:
            return
        if self._runtime is None:
            raise RuntimeDriftError(
                "the runtime was never validated; a research comparison cannot be "
                "attributed to unchecked tools"
            )
        require_runtime_assets_unchanged(
            self._config.runtime_assets(),
            self._runtime,
            label="MINDTCT/MCC runtime asset",
        )

    # -------------------------------------------------------------- compare

    def compare(
        self, left: PreparedImage, right: PreparedImage, context: ComparisonContext
    ) -> RawMatchResult:
        """Stage, extract twice, translate twice, match once, leave nothing behind.

        ``left`` is the probe and ``right`` the candidate, fixed. Stage 20A proved
        the SDK symmetric on its own samples, which is why this route can be one
        ordinary invocation: there is no reversal here, no mean of the two
        directions and no maximum of them.
        """
        self.check_runtime_integrity()

        workspace = AdapterJobWorkspace.from_context(context)
        budget = _Budget(context.timeout_seconds)
        timings: dict[str, float] = {}
        counts: dict[str, str] = {}

        failure: FailureInfo | None = None
        score: float | None = None
        try:
            started = perf_counter_ns()
            left_input, left_raster = self._stage(left, workspace, LEFT_INPUT, "left")
            right_input, right_raster = self._stage(
                right, workspace, RIGHT_INPUT, "right"
            )
            timings["input_staging"] = (perf_counter_ns() - started) / _NS_PER_MS

            left_minutiae = self._extract(
                side="left", source=left_input, output_root=LEFT_OUTPUT_ROOT,
                raster=left_raster, workspace=workspace, budget=budget,
                timings=timings, counts=counts,
            )
            # Independently, even when both sides are the same file.
            right_minutiae = self._extract(
                side="right", source=right_input, output_root=RIGHT_OUTPUT_ROOT,
                raster=right_raster, workspace=workspace, budget=budget,
                timings=timings, counts=counts,
            )

            left_side = self._translate(
                side="left", minutiae=left_minutiae, raster=left_raster, timings=timings
            )
            right_side = self._translate(
                side="right", minutiae=right_minutiae, raster=right_raster, timings=timings
            )
            score = self._match(
                left=left_side, right=right_side, workspace=workspace,
                budget=budget, timings=timings,
            )
        except _StageFailure as stage_failure:
            failure = stage_failure.info
        finally:
            cleanup_started = perf_counter_ns()
            try:
                self._cleanup(workspace)
            finally:
                timings["cleanup"] = (perf_counter_ns() - cleanup_started) / _NS_PER_MS

        if failure is not None:
            return RawMatchResult.failed(
                failure=failure,
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                artifacts=(),
                timing_components_ms=timings,
                metadata={**RESULT_METADATA, **counts},
            )
        return RawMatchResult.success(
            raw_score=float(score),
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=(),
            timing_components_ms=timings,
            metadata={
                **RESULT_METADATA,
                **counts,
                "extraction_count": "2",
                "mcc_template_count": "2",
                STATUS_KEY: "OK",
            },
        )

    # --------------------------------------------------------------- stages

    def _stage(
        self, image: PreparedImage, workspace: AdapterJobWorkspace, name: str, side: str
    ):
        """Check the input contract, then copy the file byte for byte."""
        try:
            raster = require_gray8_500ppi_png(image)
        except NbisInputRejected as rejected:
            raise _StageFailure(
                FailureInfo(
                    code=FailureCode.INPUT_INVALID,
                    stage=FailureStage.INPUT,
                    message="the prepared image is not a gray8 500 ppi PNG",
                    details={
                        "side": side,
                        "reason": rejected.reason,
                        STATUS_KEY: "INFRASTRUCTURE_FAILURE",
                    },
                )
            ) from rejected

        target = workspace.work_path(name)
        try:
            shutil.copyfile(Path(image.local_path), target)
        except OSError as exc:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.INPUT,
                    code=FailureCode.INTERNAL_ERROR,
                    detail=type(exc).__name__,
                )
            ) from exc
        return target, raster

    def _extract(
        self, *, side: str, source: Path, output_root: str, raster,
        workspace: AdapterJobWorkspace, budget: _Budget,
        timings: dict[str, float], counts: dict[str, str],
    ):
        """``mindtct <input.png> <output-root>``, and nothing else on the line."""
        root = workspace.work_path(output_root)
        result = self._run(
            argv=(str(self._config.mindtct_executable), str(source), str(root)),
            workspace=workspace, budget=budget, tool=MINDTCT_TOOL,
            stage=EXTRACTION_STAGE,
        )
        timings[f"mindtct_{side}"] = result.duration_ms

        if result.launch_failed:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.EXTRACTION,
                    code=FailureCode.DEPENDENCY_MISSING,
                    detail="mindtct_launch",
                )
            )
        if result.timed_out:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.TIMEOUT,
                    code=FailureCode.TIMEOUT,
                    detail="mindtct_timeout",
                )
            )
        if is_process_crash(result.exit_code):
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.EXTRACTION,
                    code=FailureCode.PROCESS_CRASHED,
                    detail=f"mindtct_crash_{int(result.exit_code or 0)}",
                )
            )
        if result.exit_code != 0:
            raise _StageFailure(
                mindtct_failure(side=side, exit_code=int(result.exit_code or 0))
            )

        template = workspace.work_path(f"{output_root}.xyt")
        try:
            minutiae = read_xyt(
                template, image_width=raster.width, image_height=raster.height
            )
        except XytFormatError as exc:
            raise _StageFailure(invalid_xyt_failure(side=side, kind=exc.kind)) from exc
        counts[f"{side}_minutiae_count"] = str(len(minutiae))
        return minutiae

    def _translate(self, *, side: str, minutiae, raster, timings: dict[str, float]):
        """XYT minutiae -> one MCC payload side. A representation change, nothing more."""
        started = perf_counter_ns()
        try:
            translated = translate_xyt_to_mcc_input(
                minutiae, width=raster.width, height=raster.height
            )
        except MccTranslationRefused as refused:
            timings[f"translation_{side}"] = (perf_counter_ns() - started) / _NS_PER_MS
            raise _StageFailure(
                template_refused_failure(side=side, reason=refused.reason)
            ) from refused
        timings[f"translation_{side}"] = (perf_counter_ns() - started) / _NS_PER_MS
        return translated

    def _match(
        self, *, left, right, workspace: AdapterJobWorkspace,
        budget: _Budget, timings: dict[str, float],
    ) -> float:
        """``bridge match <payload>`` — two templates, one match, one number.

        The bridge is handed a payload and hands back a line. Nothing on either
        side of that call filters, sorts, thresholds or transforms; the only
        arithmetic this method does is turning the bridge's microseconds into
        the milliseconds every other adapter reports.
        """
        payload = workspace.work_path(PAYLOAD_NAME)
        try:
            payload.write_text(render_bridge_payload(left, right), encoding="ascii")
        except OSError as exc:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.MATCHING,
                    code=FailureCode.INTERNAL_ERROR,
                    detail=type(exc).__name__,
                )
            ) from exc

        # The bridge is executed by its Linux name — that is how WSL interop
        # starts it — but reads the payload as a Windows process, so the argument
        # crosses the boundary and the executable does not.
        try:
            payload_argument = windows_path(payload)
        except InteropPathUnreachable as unreachable:
            raise _StageFailure(
                bridge_failure(detail="workspace_not_visible_to_windows")
            ) from unreachable

        result = self._run(
            argv=(str(self._config.mcc_bridge), "match", payload_argument),
            workspace=workspace, budget=budget, tool="mcc_bridge", stage="matching",
        )

        if result.launch_failed:
            raise _StageFailure(mcc_runtime_failure(detail="bridge_launch"))
        if result.timed_out:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.TIMEOUT,
                    code=FailureCode.TIMEOUT,
                    detail="mcc_bridge_timeout",
                )
            )
        if is_process_crash(result.exit_code):
            raise _StageFailure(
                mcc_runtime_failure(detail=f"bridge_crash_{int(result.exit_code or 0)}")
            )

        # Split the lines first and never strip the line itself: the last field is
        # empty on the success path, so stripping would eat its tab and turn a
        # perfectly good answer into an unreadable one.
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise _StageFailure(bridge_failure(detail="no_bridge_output"))
        fields = lines[-1].split("\t")
        if len(fields) != len(BRIDGE_OUTPUT_FIELDS):
            raise _StageFailure(bridge_failure(detail="unreadable_bridge_output"))
        report = dict(zip(BRIDGE_OUTPUT_FIELDS, fields))

        self._record_bridge_timings(report, timings)

        status = report["status"]
        if status not in STAGE20B_STATUSES:
            raise _StageFailure(bridge_failure(detail="unknown_bridge_status"))
        if status.startswith("MCC_TEMPLATE_REFUSAL"):
            side = status.rsplit("_", 1)[-1].lower()
            raise _StageFailure(
                template_refused_failure(side=side, reason=report["detail"] or "sdk_refusal")
            )
        if status == "MCC_MATCH_REFUSAL":
            raise _StageFailure(
                match_refused_failure(detail=report["detail"] or "sdk_refusal")
            )
        if status == "MCC_INVALID_SCORE":
            raise _StageFailure(invalid_score_failure(observed=report["score"]))
        if status == "MCC_RUNTIME_FAILURE":
            raise _StageFailure(
                mcc_runtime_failure(detail=report["detail"] or "clr_failure")
            )
        if status == "BRIDGE_FAILURE":
            raise _StageFailure(
                bridge_failure(detail=report["detail"] or "bridge_refusal")
            )
        if status != "OK" or result.exit_code != 0:
            raise _StageFailure(bridge_failure(detail="unexpected_bridge_state"))

        try:
            score = float(report["score"])
        except ValueError:
            raise _StageFailure(bridge_failure(detail="unreadable_score")) from None

        # Belt and braces: the bridge already refuses to call a value OK unless
        # it is finite and inside the contract, and this side refuses to accept
        # one anyway. Neither side clamps.
        if not SCORE_MINIMUM <= score <= SCORE_MAXIMUM or score != score:
            raise _StageFailure(invalid_score_failure(observed=report["score"]))
        return score

    def _record_bridge_timings(
        self, report: Mapping[str, str], timings: dict[str, float]
    ) -> None:
        """The SDK's own template and match costs, in milliseconds.

        Absent or unreadable timings are dropped rather than raised: a stored
        result missing one duration is a smaller loss than a comparison thrown
        away because a stopwatch would not parse.
        """
        for field, name in (
            ("template_left_us", "mcc_template_left"),
            ("template_right_us", "mcc_template_right"),
            ("match_us", "mcc_match"),
        ):
            text = report.get(field, "")
            if not text:
                continue
            try:
                timings[name] = float(text) / 1000.0
            except ValueError:
                continue

    def _run(
        self, *, argv: tuple[str, ...], workspace: AdapterJobWorkspace,
        budget: _Budget, tool: str, stage: str,
    ) -> ExternalCommandResult:
        remaining = budget.remaining()
        if remaining <= 0:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.TIMEOUT,
                    code=FailureCode.TIMEOUT,
                    detail=f"{tool}_{stage}_budget",
                )
            )
        return run_external_command(
            ExternalCommand(
                argv=argv,
                working_directory=workspace.working_directory,
                containment_root=workspace.working_directory,
                timeout_seconds=remaining,
            )
        )

    def _cleanup(self, workspace: AdapterJobWorkspace) -> None:
        """Remove everything this comparison wrote, on every path out."""
        directory = workspace.working_directory
        names = {LEFT_INPUT, RIGHT_INPUT, PAYLOAD_NAME}
        roots = (LEFT_OUTPUT_ROOT, RIGHT_OUTPUT_ROOT)

        def _is_ours(entry_name: str) -> bool:
            return entry_name in names or any(
                entry_name == root or entry_name.startswith(f"{root}.")
                for root in roots
            )

        for entry in list(directory.iterdir()):
            if _is_ours(entry.name):
                try:
                    entry.unlink()
                except OSError:
                    pass
        survivors = [
            entry.name for entry in directory.iterdir() if _is_ours(entry.name)
        ]
        if survivors:
            raise MccCleanupError(
                f"{len(survivors)} file(s) this comparison wrote are still on disk"
            )
