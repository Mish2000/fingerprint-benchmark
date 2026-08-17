"""MINDTCT into OpenAFIS, behind the same three methods as everything else.

.. code-block:: text

    left  PreparedImage -> byte-for-byte copy -> mindtct -> left-nbis.xyt
    right PreparedImage -> byte-for-byte copy -> mindtct -> right-nbis.xyt
    each .xyt           -> mechanical CSV translation -> OpenAFIS template
    both templates      -> MatchSimilarity           -> raw uint8_t score

**The identity is the whole route.** ``nbis_mindtct_openafis``, because the
extractor is half of what makes a score and this route shares that half with
Algorithm 2. Algorithms 2 and 5 differ *only* in their matcher, which is exactly
what makes the pair interesting — and exactly why the difference must be stated
rather than presented as two independent systems.

**MINDTCT runs the way Algorithm 2 runs it.** ``mindtct <input.png> <root>``, no
``-b``, no ``-m1``, no quality cutoff, no preprocessing, and the canonical 500 ppi
PNG copied byte for byte. There is no resize, no crop and no return to 300x400
here: Stage 18A's distorting route belonged to the helper it was transcribed
from, and nothing of it survives into Algorithm 5.

**SELF is two independent extractions.** The same image on both sides gets two
separate MINDTCT invocations writing to two separate roots, exactly as the NBIS
route does. No cache, no template reuse — an adapter that noticed both sides were
the same file and answered from one extraction would be measuring itself.

**Nothing here was chosen by looking at Stage 18A's scores.** The angle
convention is derived in :mod:`fpbench.adapters.openafis.translation` from NBIS's
``xytreps.c`` and OpenAFIS's ``TripletScalar.cpp``; the minutia type is proved
non-score-bearing by test; quality is dropped because OpenAFIS has nowhere to put
it. See ``docs/adr/0135``.

**A score of 0 is a success.** OpenAFIS leaves its result at 0 when two templates
share too little structure. That is an answer about two fingers, and this adapter
never turns it into a failure or a failure into it.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from time import perf_counter_ns
from typing import Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.errors import AdapterError
from fpbench.adapters.nbis.adapter import VERSION_PROBES, version_probe
from fpbench.adapters.nbis.build_manifest import (
    EXPECTED_NBIS_VERSION,
    SUPPORTED_TARGETS,
    NbisBuildManifest,
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
from fpbench.adapters.openafis.config import (
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
    OPENAFIS_BRIDGE_ROLE,
    RUNTIME_ASSET_ROLES,
    OpenAfisConfig,
)
from fpbench.adapters.openafis.failure_mapping import (
    STAGE19_STATUSES,
    infrastructure_failure,
    invalid_xyt_failure,
    mindtct_failure,
    openafis_match_failure,
    template_refused_failure,
)
from fpbench.adapters.openafis.translation import (
    ANGLE_CONVERSION,
    MINUTIA_TYPE_POLICY,
    OPENAFIS_MAXIMUM_MINUTIAE,
    OPENAFIS_MINIMUM_MINUTIAE,
    PLACEHOLDER_MINUTIA_TYPE,
    TranslationRefused,
    translate_xyt_to_openafis_csv,
)
from fpbench.adapters.pipeline_metadata import AlgorithmPipelineMetadata
from fpbench.adapters.support.process import ExternalCommand, ExternalCommandResult, run_external_command
from fpbench.adapters.support.runtime_guard import (
    FileIdentity,
    require_runtime_assets_unchanged,
    snapshot_runtime_assets,
)
from fpbench.adapters.support.workspace import AdapterJobWorkspace
from fpbench.core.enums import EnvironmentStatus, FailureCode, FailureStage, ScoreDirection
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
    "OpenAfisAdapter",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "IMPLEMENTATION_VERSION",
    "PIPELINE_METADATA",
    "RESULT_METADATA",
    "STAGE19_STATUSES",
]

ALGORITHM_ID = "nbis_mindtct_openafis"
ADAPTER_ID = "nbis_mindtct_openafis_subprocess"
ADAPTER_VERSION = "1.0.0"
IMPLEMENTATION_VERSION = "nbis-5.0.0+openafis-3ae1c757"

LEFT_INPUT = "left-input.png"
RIGHT_INPUT = "right-input.png"
LEFT_OUTPUT_ROOT = "left-nbis"
RIGHT_OUTPUT_ROOT = "right-nbis"
LEFT_TEMPLATE = "left-openafis.csv"
RIGHT_TEMPLATE = "right-openafis.csv"

#: Everything MINDTCT writes beside its output root, plus the two CSV templates
#: this adapter writes. All of it is removed after every comparison.
MINDTCT_OUTPUT_SUFFIXES: tuple[str, ...] = (
    ".brw", ".dm", ".hcm", ".lcm", ".lfm", ".min", ".qm", ".xyt",
)

OPENAFIS_COMMIT = "3ae1c757c6dafea977a33ef51380e37f1715e626"

PIPELINE = AlgorithmPipelineMetadata(
    # Deliberately not "nbis": the family is the composition, and calling it nbis
    # would imply the matcher is NIST's, which it is not.
    family_id="nbis_mindtct_openafis",
    pipeline_kind="extract_then_match",
    extractor_id="mindtct",
    extractor_version=EXPECTED_NBIS_VERSION,
    matcher_id="openafis",
    matcher_version=OPENAFIS_COMMIT,
    implementation_language="c_and_cpp",
    integration_mode="subprocess_per_stage",
    input_mode="direct_gray8_png_byte_copy",
    dpi_policy="png_ppi_undefined_nbis_default_500",
    probe_side="left",
    template_cache="disabled",
    template_persistence="disabled",
    seed_usage="ignored_algorithm_has_no_seed",
    extra={
        # The options this route does not pass, and the four translation rules
        # that were settled from source. Named so that changing one later is
        # visibly a different identity rather than a quiet edit (docs/adr/0135).
        "mindtct_contrast_boost": "disabled",
        "mindtct_m1": "disabled",
        "openafis_threshold": "none",
        "openafis_score_transform": "none",
        "openafis_template_format": "csv",
        "minutia_type_policy": MINUTIA_TYPE_POLICY,
        "minutiae_quality_transferred": "no",
        "minutiae_filtering": "none",
        "minutiae_ordering": "mindtct_order_preserved",
        "coordinate_scaling": "none",
        "angle_conversion": ANGLE_CONVERSION,
        "openafis_minutiae_bounds": f"{OPENAFIS_MINIMUM_MINUTIAE}..{OPENAFIS_MAXIMUM_MINUTIAE}",
        "score_type": "nonnegative_integer_similarity",
        "input_effective_ppi": "500",
        "shares_extractor_with": "nbis_mindtct_bozorth3",
        "secugen_reference_used_for_parameter_selection": "false",
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
    "openafis_commit": OPENAFIS_COMMIT,
    "input_format": "png",
    "input_depth": "8",
    "input_transport": "byte_for_byte_copy",
    "effective_ppi": "500",
    "ppi_policy": "nbis_png_default_500",
    "mindtct_mode": "default",
    "mindtct_m1": "disabled",
    "openafis_threshold": "none",
    "openafis_score_transform": "none",
    "openafis_template_format": "csv",
    "minutia_type_policy": MINUTIA_TYPE_POLICY,
    "minutiae_quality_transferred": "no",
    "minutiae_filtering": "none",
    "coordinate_scaling": "none",
    "angle_conversion": ANGLE_CONVERSION,
    "secugen_reference_used_for_parameter_selection": "false",
}

_NS_PER_MS = 1_000_000


class OpenAfisCleanupError(AdapterError):
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


class OpenAfisAdapter(FingerprintAlgorithmAdapter):
    """Compares two prepared 500 ppi greyscale PNGs with MINDTCT and OpenAFIS."""

    def __init__(self, config: OpenAfisConfig) -> None:
        self._config = config
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="NBIS MINDTCT + OpenAFIS",
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
    def from_config(cls, config: Mapping[str, object]) -> "OpenAfisAdapter":
        return cls(OpenAfisConfig.from_mapping(config))

    @property
    def config(self) -> OpenAfisConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Is this the certified NBIS build, and is the OpenAFIS bridge runnable?

        The NBIS half is checked exactly as the NBIS route checks it — same
        manifest, same version probe — because Algorithm 5 claiming a different
        extractor identity from Algorithm 2 while running the same binary would
        make the one interesting comparison in this pair unreadable.
        """
        self._runtime = None

        host = host_target()
        if host not in SUPPORTED_TARGETS:
            return self._unavailable(
                f"this build of NBIS runs on {sorted(SUPPORTED_TARGETS)} and this machine is {host[0]}/{host[1]}"
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

        observed = version_probe(self._config.mindtct_executable, VERSION_PROBES[MINDTCT_TOOL])
        if observed is None:
            return self._unavailable("mindtct could not be run")
        if observed != manifest.mindtct_version_output:
            return self._manifest_problem(
                "mindtct no longer answers its version probe the way the build manifest recorded"
            )

        bridge = self._probe_bridge()
        if bridge is None:
            return self._unavailable("the openafis bridge could not be run")

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
                "openafis.instruction_set": bridge.get("openafis_instruction_set", ""),
            },
            dependencies={
                "nbis.version": manifest.nbis_version,
                "nbis.build_manifest_fingerprint": manifest.manifest_fingerprint,
                "nbis.mindtct.sha256": manifest.mindtct_sha256,
                "nbis.mindtct.size": str(manifest.mindtct_size_bytes),
                "nbis.official_tests.passed": str(summary.passed_tests),
                "openafis.commit": OPENAFIS_COMMIT,
                "openafis.score_native_type": bridge.get("score_native_type", ""),
                "openafis.score_transform": bridge.get("score_transform", ""),
                "openafis.threshold": bridge.get("threshold", ""),
                "openafis.param_minimum_minutiae": bridge.get("param_minimum_minutiae", ""),
                "openafis.minutiae_bounds": f"{OPENAFIS_MINIMUM_MINUTIAE}..{OPENAFIS_MAXIMUM_MINUTIAE}",
            },
        )

    def _probe_bridge(self) -> dict[str, str] | None:
        """Ask the bridge what it is. Returns its key/value report, or None."""
        result = run_external_command(
            ExternalCommand(
                argv=(str(self._config.openafis_bridge), "identity"),
                working_directory=Path(self._config.openafis_bridge).parent,
                containment_root=Path(self._config.openafis_bridge).parent,
                timeout_seconds=30.0,
            )
        )
        if result.launch_failed or result.timed_out or result.exit_code != 0:
            return None
        report: dict[str, str] = {}
        for line in result.stdout.splitlines():
            if "\t" in line:
                key, value = line.split("\t", 1)
                report[key.strip()] = value.strip()
        return report

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
            self._config.runtime_assets(), self._runtime, label="MINDTCT/OpenAFIS runtime asset"
        )

    # -------------------------------------------------------------- compare

    def compare(
        self, left: PreparedImage, right: PreparedImage, context: ComparisonContext
    ) -> RawMatchResult:
        """Stage, extract twice, translate twice, match once, leave nothing behind.

        ``left`` is the probe and ``right`` the candidate, fixed — the same
        orientation Stage 18A froze and the same one the bridge encodes. No
        reversal, no averaging of the two directions, no maximum of the two.
        """
        self.check_runtime_integrity()

        workspace = AdapterJobWorkspace.from_context(context)
        budget = _Budget(context.timeout_seconds)
        timings: dict[str, float] = {}
        counts: dict[str, str] = {}

        failure: FailureInfo | None = None
        score: int | None = None
        try:
            started = perf_counter_ns()
            left_input, left_raster = self._stage(left, workspace, LEFT_INPUT, "left")
            right_input, right_raster = self._stage(right, workspace, RIGHT_INPUT, "right")
            timings["input_staging"] = (perf_counter_ns() - started) / _NS_PER_MS

            left_minutiae = self._extract(
                side="left", source=left_input, output_root=LEFT_OUTPUT_ROOT,
                raster=left_raster, workspace=workspace, budget=budget, timings=timings, counts=counts,
            )
            # Independently, even when both sides are the same file.
            right_minutiae = self._extract(
                side="right", source=right_input, output_root=RIGHT_OUTPUT_ROOT,
                raster=right_raster, workspace=workspace, budget=budget, timings=timings, counts=counts,
            )

            left_template = self._translate(
                side="left", minutiae=left_minutiae, raster=left_raster,
                workspace=workspace, name=LEFT_TEMPLATE, timings=timings,
            )
            right_template = self._translate(
                side="right", minutiae=right_minutiae, raster=right_raster,
                workspace=workspace, name=RIGHT_TEMPLATE, timings=timings,
            )
            score = self._match(
                left_template=left_template, right_template=right_template,
                workspace=workspace, budget=budget, timings=timings,
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
            metadata={**RESULT_METADATA, **counts, "extraction_count": "2", "stage19_status": "OK"},
        )

    # --------------------------------------------------------------- stages

    def _stage(self, image: PreparedImage, workspace: AdapterJobWorkspace, name: str, side: str):
        """Check the input contract, then copy the file byte for byte."""
        try:
            raster = require_gray8_500ppi_png(image)
        except NbisInputRejected as rejected:
            raise _StageFailure(
                FailureInfo(
                    code=FailureCode.INPUT_INVALID,
                    stage=FailureStage.INPUT,
                    message="the prepared image is not a gray8 500 ppi PNG",
                    details={"side": side, "reason": rejected.reason, "stage19_status": "INFRASTRUCTURE_FAILURE"},
                )
            ) from rejected

        target = workspace.work_path(name)
        try:
            shutil.copyfile(Path(image.local_path), target)
        except OSError as exc:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.INPUT, code=FailureCode.INTERNAL_ERROR, detail=type(exc).__name__
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
            workspace=workspace, budget=budget, tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE,
        )
        timings[f"mindtct_{side}"] = result.duration_ms

        if result.launch_failed:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.EXTRACTION, code=FailureCode.DEPENDENCY_MISSING, detail="mindtct_launch"
                )
            )
        if result.timed_out:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.TIMEOUT, code=FailureCode.TIMEOUT, detail="mindtct_timeout"
                )
            )
        if is_process_crash(result.exit_code):
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.EXTRACTION, code=FailureCode.PROCESS_CRASHED,
                    detail=f"mindtct_crash_{int(result.exit_code or 0)}",
                )
            )
        if result.exit_code != 0:
            raise _StageFailure(mindtct_failure(side=side, exit_code=int(result.exit_code or 0)))

        template = workspace.work_path(f"{output_root}.xyt")
        try:
            minutiae = read_xyt(template, image_width=raster.width, image_height=raster.height)
        except XytFormatError as exc:
            raise _StageFailure(invalid_xyt_failure(side=side, kind=exc.kind)) from exc
        counts[f"{side}_minutiae_count"] = str(len(minutiae))
        return minutiae

    def _translate(
        self, *, side: str, minutiae, raster, workspace: AdapterJobWorkspace,
        name: str, timings: dict[str, float],
    ) -> Path:
        """XYT minutiae -> one OpenAFIS CSV template. A format change, nothing more."""
        started = perf_counter_ns()
        try:
            translated = translate_xyt_to_openafis_csv(
                minutiae, width=raster.width, height=raster.height,
                minutia_type=PLACEHOLDER_MINUTIA_TYPE,
            )
        except TranslationRefused as refused:
            timings[f"openafis_template_{side}"] = (perf_counter_ns() - started) / _NS_PER_MS
            raise _StageFailure(template_refused_failure(side=side, reason=refused.reason)) from refused

        target = workspace.work_path(name)
        try:
            target.write_text(translated.text, encoding="ascii")
        except OSError as exc:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.EXTRACTION, code=FailureCode.INTERNAL_ERROR, detail=type(exc).__name__
                )
            ) from exc
        timings[f"openafis_template_{side}"] = (perf_counter_ns() - started) / _NS_PER_MS
        return target

    def _match(
        self, *, left_template: Path, right_template: Path,
        workspace: AdapterJobWorkspace, budget: _Budget, timings: dict[str, float],
    ) -> int:
        """``bridge match <probe.csv> <candidate.csv> --format csv``.

        No threshold and no options that could filter: the bridge calls
        ``MatchSimilarity::compute`` and prints the ``uint8_t`` it produced.
        """
        result = self._run(
            argv=(
                str(self._config.openafis_bridge), "match",
                str(left_template), str(right_template), "--format", "csv",
            ),
            workspace=workspace, budget=budget, tool="openafis", stage="matching",
        )

        if result.launch_failed:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.MATCHING, code=FailureCode.DEPENDENCY_MISSING, detail="openafis_launch"
                )
            )
        if result.timed_out:
            raise _StageFailure(
                infrastructure_failure(stage=FailureStage.TIMEOUT, code=FailureCode.TIMEOUT, detail="openafis_timeout")
            )
        if is_process_crash(result.exit_code) or result.exit_code != 0:
            raise _StageFailure(openafis_match_failure(detail=f"exit_{int(result.exit_code or 0)}"))

        fields = result.stdout.strip().split("\t")
        if len(fields) < 6:
            raise _StageFailure(openafis_match_failure(detail="unreadable_bridge_output"))
        _id, status, raw, load_left_us, load_right_us, match_us = fields[:6]

        # The bridge measures OpenAFIS's own template construction — parse,
        # Delaunay, triplets — which is the cost the requirement asks for and is
        # not the same thing as the CSV write above.
        try:
            timings["openafis_template_left"] = timings.get("openafis_template_left", 0.0) + int(load_left_us) / 1000.0
            timings["openafis_template_right"] = timings.get("openafis_template_right", 0.0) + int(load_right_us) / 1000.0
            timings["openafis_match"] = int(match_us) / 1000.0
        except ValueError:
            raise _StageFailure(openafis_match_failure(detail="unreadable_bridge_timings")) from None

        if status != "OK":
            # The bridge distinguishes which side failed to load; both sides
            # already passed the 2..128 check, so this is OpenAFIS refusing a
            # template the bridge believed in.
            side = "both"
            if status.endswith("_LEFT"):
                side = "left"
            elif status.endswith("_RIGHT"):
                side = "right"
            if status.startswith("LOAD_FAILED") or status.startswith("NO_FINGERPRINT"):
                raise _StageFailure(template_refused_failure(side=side, reason=status.lower()))
            raise _StageFailure(openafis_match_failure(detail=status.lower()))

        try:
            return int(raw)
        except ValueError:
            raise _StageFailure(openafis_match_failure(detail="unreadable_score")) from None

    def _run(
        self, *, argv: tuple[str, ...], workspace: AdapterJobWorkspace,
        budget: _Budget, tool: str, stage: str,
    ) -> ExternalCommandResult:
        remaining = budget.remaining()
        if remaining <= 0:
            raise _StageFailure(
                infrastructure_failure(
                    stage=FailureStage.TIMEOUT, code=FailureCode.TIMEOUT, detail=f"{tool}_{stage}_budget"
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
        names = {LEFT_INPUT, RIGHT_INPUT, LEFT_TEMPLATE, RIGHT_TEMPLATE}
        roots = (LEFT_OUTPUT_ROOT, RIGHT_OUTPUT_ROOT)
        for entry in list(directory.iterdir()):
            if entry.name in names or any(
                entry.name == root or entry.name.startswith(f"{root}.") for root in roots
            ):
                try:
                    entry.unlink()
                except OSError:
                    pass
        survivors = [
            entry.name
            for entry in directory.iterdir()
            if entry.name in names
            or any(entry.name == root or entry.name.startswith(f"{root}.") for root in roots)
        ]
        if survivors:
            raise OpenAfisCleanupError(
                f"{len(survivors)} file(s) this comparison wrote are still on disk"
            )
