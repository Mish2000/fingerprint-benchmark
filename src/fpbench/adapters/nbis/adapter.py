"""MINDTCT into BOZORTH3, behind the same three methods as everything else.

One comparison is four things: stage two PNGs, extract a template from each with
MINDTCT, hand the two templates to BOZORTH3, read one integer. It reaches the
runner through ``descriptor``, ``validate_environment`` and ``compare``, exactly
as the dummy matcher does, and ``SingleJobRunner`` gains no extractor, no matcher,
no template store and no knowledge that this route has stages at all
(docs/adr/0039, docs/adr/0043).

    left  PreparedImage -> byte-for-byte copy -> mindtct -> left-nbis.xyt
    right PreparedImage -> byte-for-byte copy -> mindtct -> right-nbis.xyt
    left-nbis.xyt + right-nbis.xyt            -> bozorth3 -> raw score

**The identity is the whole route.** ``nbis_mindtct_bozorth3``, not ``bozorth3``:
two runs against different MINDTCT builds would otherwise share an identity they
are not entitled to, and the extractor is where most of the decisions are made
(docs/adr/0014, docs/adr/0046).

**Every tool option is part of that identity, including the ones not passed.**
MINDTCT runs with no flags — no ``-b``, no ``-m1`` — and BOZORTH3 runs with none
at all, which means its documented defaults of 150 maximum and 10 minimum
minutiae. Those are not knobs of this identity; ``mindtct -b`` is a different
algorithmic route and would need a different identity, and ``bozorth3 -T`` is not
a raw-score route at all because it filters the output it prints
(docs/adr/0049, spec sections 15, 25 and 26).

**Both sides are extracted independently, always.** A SELF comparison hands in the
same image twice and gets two separate MINDTCT invocations writing to two separate
output roots. Reusing the first would make SELF the one stage that took a
different code path — and SELF exists precisely to detect the failures that have
nothing to do with cross-impression matching (docs/adr/0035, docs/adr/0050).

**Nothing survives the comparison.** The staged inputs, both templates and every
map file MINDTCT writes beside them are removed in a ``finally``, on success and
on every failure alike. There is no template cache, no template store and no
published XYT: an intermediate is a detail of how a score was computed, not
evidence (docs/adr/0041, docs/adr/0050, spec section 32).

**0 is a score.** BOZORTH3 returns 0 when a side has fewer than ten minutiae, and
for two templates with no compatible structure. Neither is a failure. What a 0
means biometrically is a question for the decision stage, over stored scores
(docs/adr/0006).
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path
from time import perf_counter_ns
from typing import Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
from fpbench.adapters.nbis.build_manifest import (
    EXPECTED_NBIS_VERSION,
    SUPPORTED_TARGETS,
    NbisBuildManifest,
    NbisBuildManifestError,
    host_target,
    read_build_manifest,
    verify_build_manifest,
)
from fpbench.adapters.nbis.config import (
    BOZORTH3_ROLE,
    BUILD_MANIFEST_ROLE,
    MINDTCT_ROLE,
    PRIMARY_RUNTIME_ASSET_ROLE,
    RUNTIME_ASSET_ROLES,
    NbisConfig,
)
from fpbench.adapters.nbis.failure_mapping import (
    BOZORTH3_TOOL,
    EXTRACTION_STAGE,
    MATCHING_STAGE,
    MINDTCT_TOOL,
    crash_failure,
    extraction_exit_failure,
    input_rejected_failure,
    invalid_extractor_output_failure,
    is_process_crash,
    launch_failure,
    matching_exit_failure,
    no_score_failure,
    timeout_failure,
)
from fpbench.adapters.nbis.png_input import (
    NbisInputRejected,
    require_gray8_500ppi_png,
)
from fpbench.adapters.nbis.score import ScoreFormatError, parse_bozorth3_score
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
from fpbench.core.enums import EnvironmentStatus, ScoreDirection
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
    "NbisAdapter",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "IMPLEMENTATION_VERSION",
    "PIPELINE",
    "PIPELINE_METADATA",
    "RESULT_METADATA",
    "MINDTCT_ROLE",
    "BOZORTH3_ROLE",
    "BUILD_MANIFEST_ROLE",
    "RUNTIME_ASSET_ROLES",
    "PRIMARY_RUNTIME_ASSET_ROLE",
    "MINDTCT_OUTPUT_SUFFIXES",
    "LEFT_INPUT",
    "RIGHT_INPUT",
    "LEFT_OUTPUT_ROOT",
    "RIGHT_OUTPUT_ROOT",
    "VERSION_PROBES",
    "version_probe",
]

#: The route, not the matcher. Renaming it would be renaming the experiment.
ALGORITHM_ID = "nbis_mindtct_bozorth3"
ADAPTER_ID = "nbis_mindtct_bozorth3_subprocess"

#: This wrapper's version. Moves when the wrapper changes; the NBIS version
#: underneath it moves separately, which is the whole point of having two.
ADAPTER_VERSION = "1"
IMPLEMENTATION_VERSION = EXPECTED_NBIS_VERSION

#: The identity of the whole route. Every value here is a decision that would
#: change scores if it changed, which is why none of them is configurable.
PIPELINE = AlgorithmPipelineMetadata(
    family_id="nbis",
    pipeline_kind="extract_then_match",
    extractor_id="mindtct",
    extractor_version=EXPECTED_NBIS_VERSION,
    matcher_id="bozorth3",
    matcher_version=EXPECTED_NBIS_VERSION,
    implementation_language="c",
    integration_mode="subprocess_per_stage",
    input_mode="direct_gray8_png_byte_copy",
    dpi_policy="png_ppi_undefined_nbis_default_500",
    probe_side="left",
    template_cache="disabled",
    template_persistence="disabled",
    seed_usage="ignored_algorithm_has_no_seed",
    extra={
        # The options this route does not pass, named so that passing one later
        # is visibly a different identity rather than a quiet change
        # (docs/adr/0049).
        "mindtct_contrast_boost": "disabled",
        "mindtct_m1": "disabled",
        "bozorth3_m1": "disabled",
        "bozorth3_threshold": "none",
        "bozorth3_max_minutiae": "default_150",
        "bozorth3_min_minutiae": "default_10",
        "score_type": "nonnegative_integer_similarity",
        "input_effective_ppi": "500",
    },
)

#: The descriptor metadata as a plain mapping, for the validator to compare
#: against without rebuilding the adapter.
PIPELINE_METADATA: Mapping[str, str] = PIPELINE.as_descriptor_metadata()

#: What every stored result records about how this score was produced. Fixed for
#: the identity; the per-comparison keys are added beside it (spec section 33).
RESULT_METADATA: Mapping[str, str] = {
    "pipeline": ALGORITHM_ID,
    "nbis_version": EXPECTED_NBIS_VERSION,
    "input_format": "png",
    "input_depth": "8",
    "input_transport": "byte_for_byte_copy",
    "effective_ppi": "500",
    "ppi_policy": "nbis_png_default_500",
    "probe_side": "left",
    "mindtct_mode": "default",
    "mindtct_contrast_boost": "disabled",
    "mindtct_m1": "disabled",
    "bozorth3_mode": "default_one_to_one",
    "bozorth3_m1": "disabled",
    "bozorth3_threshold": "none",
    "bozorth3_max_minutiae": "150",
    "bozorth3_min_minutiae": "10",
    "extraction_policy": "independent_both_sides",
    "template_cache": "disabled",
    "template_persistence": "disabled",
}

#: Intermediate file names. Deliberately meaningless: the adapter has no subject,
#: no finger and no pair, and a name that carried one would mean it had been
#: given something it must not have (docs/adr/0010).
LEFT_INPUT = "left-input.png"
RIGHT_INPUT = "right-input.png"
LEFT_OUTPUT_ROOT = "left-nbis"
RIGHT_OUTPUT_ROOT = "right-nbis"

#: Everything MINDTCT writes beside its output root. All of it is removed; the
#: XYT is the only one this route reads, and none of them is evidence.
MINDTCT_OUTPUT_SUFFIXES: tuple[str, ...] = (
    "xyt",
    "min",
    "brw",
    "dm",
    "hcm",
    "lcm",
    "lfm",
    "qm",
)

#: The version probe each tool is asked. Fixed, and recorded in the build
#: manifest by the same commands, so the check is that the answer is *stable*.
VERSION_PROBES: Mapping[str, tuple[str, ...]] = {
    MINDTCT_TOOL: ("-version",),
    BOZORTH3_TOOL: ("-V",),
}

_NS_PER_MS = 1_000_000

#: Never let a stage run to zero budget: a zero timeout is not a valid command,
#: and "there was no time left" is a timeout rather than a configuration error.
_MINIMUM_BUDGET_SECONDS = 0.001

_VERSION_PROBE_TIMEOUT_SECONDS = 60.0

_READ_CHUNK = 1 << 20


class _StageFailure(Exception):
    """Internal: stop the comparison and record ``info``."""

    def __init__(self, info: FailureInfo) -> None:
        super().__init__(info.message)
        self.info = info


class NbisAdapter(FingerprintAlgorithmAdapter):
    """Compares two prepared 500 ppi greyscale PNGs with MINDTCT and BOZORTH3."""

    def __init__(self, config: NbisConfig) -> None:
        self._config = config
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="NBIS MINDTCT + BOZORTH3",
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=IMPLEMENTATION_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            capabilities=(),
            metadata=PIPELINE_METADATA,
        )
        #: Taken during environment validation, compared before every comparison.
        self._runtime: Mapping[str, FileIdentity] | None = None

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "NbisAdapter":
        return cls(NbisConfig.from_mapping(config))

    @property
    def config(self) -> NbisConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Is this a certified NBIS 5.0.0 build, and can it run here?

        Seven questions, in the order that makes the answers useful: the platform
        first, because a Linux build on Windows cannot be probed at all; then the
        three files; then the manifest; then whether the two executables still
        answer their version probes the way the manifest recorded.

        A missing file or an unsupported platform is ``UNAVAILABLE`` — one fault
        of the run, never an exception. A manifest that does not hold up is
        ``UNAVAILABLE`` in development and a ``ResearchPreflightError`` in
        research mode, because a research run pinned to an uncertified build is
        not a run whose results anyone may cite (spec sections 12 and 18).
        """
        self._runtime = None

        host = host_target()
        if host not in SUPPORTED_TARGETS:
            return self._unavailable(
                f"this build of NBIS runs on {sorted(SUPPORTED_TARGETS)} and this "
                f"machine is {host[0]}/{host[1]}"
            )

        missing = self._config.missing_runtime_assets()
        if missing:
            # No absolute path: an environment report is shown to people and
            # stored beside results.
            return self._unavailable(f"the pinned NBIS runtime is missing: {list(missing)}")

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
                f"the build targets {manifest.target_os}/"
                f"{manifest.target_architecture} and this machine is "
                f"{host[0]}/{host[1]}"
            )

        recorded = {
            MINDTCT_TOOL: manifest.mindtct_version_output,
            BOZORTH3_TOOL: manifest.bozorth3_version_output,
        }
        for tool, executable in (
            (MINDTCT_TOOL, self._config.mindtct_executable),
            (BOZORTH3_TOOL, self._config.bozorth3_executable),
        ):
            observed = version_probe(executable, VERSION_PROBES[tool])
            if observed is None:
                return self._unavailable(f"{tool} could not be run")
            if observed != recorded[tool]:
                return self._manifest_problem(
                    f"{tool} no longer answers its version probe the way the build "
                    "manifest recorded"
                )

        try:
            self._runtime = snapshot_runtime_assets(self._config.runtime_assets())
        except RuntimeDriftError as exc:  # pragma: no cover - it existed a moment ago
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
                "nbis.compiler_target": manifest.compiler_target,
            },
            dependencies={
                "nbis.version": manifest.nbis_version,
                "nbis.build_manifest_fingerprint": manifest.manifest_fingerprint,
                "nbis.mindtct.sha256": manifest.mindtct_sha256,
                "nbis.mindtct.size": str(manifest.mindtct_size_bytes),
                "nbis.bozorth3.sha256": manifest.bozorth3_sha256,
                "nbis.bozorth3.size": str(manifest.bozorth3_size_bytes),
                "nbis.png_ppi_policy": manifest.png_ppi_policy,
                "nbis.official_tests.passed": str(summary.passed_tests),
                "nbis.official_tests.suite": summary.ordered_output_hash,
            },
        )

    def build_manifest(self) -> NbisBuildManifest:
        """The pinned build's manifest, read and checked.

        Raises:
            NbisBuildManifestError: it is absent, malformed, or does not describe
                the two executables beside it.
        """
        manifest = read_build_manifest(self._config.build_manifest)
        verify_build_manifest(
            manifest,
            mindtct=self._config.mindtct_executable,
            bozorth3=self._config.bozorth3_executable,
        )
        return manifest

    def check_runtime_integrity(self) -> None:
        """Confirm all three files are still the ones preflight approved.

        Three ``stat`` calls, not three re-hashes: this runs before every
        comparison and the full digest runs before and after the executor.
        Outside research mode there is nothing pinned and nothing to check.

        Raises:
            RuntimeDriftError: any of them changed. Fatal to the invocation —
                never a comparison failure (docs/adr/0018).
        """
        if not self._config.research_mode:
            return
        if self._runtime is None:
            raise RuntimeDriftError(
                "the NBIS runtime was never validated; a research comparison "
                "cannot be attributed to unchecked tools"
            )
        require_runtime_assets_unchanged(
            self._config.runtime_assets(), self._runtime, label="NBIS runtime asset"
        )

    # -------------------------------------------------------------- compare

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        """Stage, extract twice, match once, and leave nothing behind.

        ``left`` is the probe and ``right`` the gallery, fixed. No reversal, no
        averaging of the two directions, no maximum of the two — BOZORTH3's own
        documentation says the two orders are not necessarily symmetric, so
        running both and combining them would be a different measurement
        (spec section 24).

        Raises:
            RuntimeDriftError: in research mode, when one of the three pinned
                files is no longer what preflight approved. Deliberately the one
                thing this method raises instead of recording — together with
                ``PreparedImageDriftError`` for an input whose bytes changed.
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
            right_input, right_raster = self._stage(
                right, workspace, RIGHT_INPUT, "right"
            )
            timings["input_staging"] = (perf_counter_ns() - started) / _NS_PER_MS

            left_template = self._extract(
                side="left",
                source=left_input,
                output_root=LEFT_OUTPUT_ROOT,
                raster=left_raster,
                workspace=workspace,
                budget=budget,
                timings=timings,
                counts=counts,
            )
            # Independently, even when both sides are the same file. The count is
            # recorded below so that this is a fact in the stored result rather
            # than a claim in a docstring (docs/adr/0050, spec section 45).
            right_template = self._extract(
                side="right",
                source=right_input,
                output_root=RIGHT_OUTPUT_ROOT,
                raster=right_raster,
                workspace=workspace,
                budget=budget,
                timings=timings,
                counts=counts,
            )
            score = self._match(
                left_template=left_template,
                right_template=right_template,
                workspace=workspace,
                budget=budget,
                timings=timings,
            )
        except _StageFailure as stage_failure:
            failure = stage_failure.info
        finally:
            cleanup_started = perf_counter_ns()
            try:
                self._cleanup(workspace)
            finally:
                timings["cleanup"] = (
                    perf_counter_ns() - cleanup_started
                ) / _NS_PER_MS

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
            metadata={**RESULT_METADATA, **counts, "extraction_count": "2"},
        )

    # --------------------------------------------------------------- stages

    def _stage(
        self,
        image: PreparedImage,
        workspace: AdapterJobWorkspace,
        name: str,
        side: str,
    ):
        """Check the input contract, then copy the file byte for byte.

        No re-encoding, no greyscale conversion, no contrast change, no resize, no
        crop, no rotation, no WSQ, no JPEG, no PGM and no IHead. MINDTCT reads the
        PNG the preparer produced, unchanged — the staged copy exists only so the
        adapter never hands a tool a path outside its own directory, and it is
        proved identical to the source before it is used (spec section 21).
        """
        try:
            raster = require_gray8_500ppi_png(image)
        except NbisInputRejected as rejected:
            raise _StageFailure(
                input_rejected_failure(side=side, reason=rejected.reason)
            ) from rejected

        target = workspace.work_path(name)
        try:
            shutil.copyfile(Path(image.local_path), target)
        except OSError as exc:
            raise _StageFailure(
                launch_failure(tool="adapter", stage="input", detail=type(exc).__name__)
            ) from exc

        expected = image.prepared_sha256 or image.expected_sha256
        digest, size = _digest_file(target)
        if digest != expected or size != raster.size_bytes:
            raise _StageFailure(
                input_rejected_failure(side=side, reason="staged_copy_differs")
            )
        return target, raster

    def _extract(
        self,
        *,
        side: str,
        source: Path,
        output_root: str,
        raster,
        workspace: AdapterJobWorkspace,
        budget: "_Budget",
        timings: dict[str, float],
        counts: dict[str, str],
    ) -> Path:
        """``mindtct <input.png> <output-root>``, and nothing else on the line.

        No ``-b`` and no ``-m1``: contrast boost and the alternative minutiae
        format are different algorithmic routes, not settings of this one
        (docs/adr/0049).
        """
        root = workspace.work_path(output_root)
        result = self._run(
            argv=(str(self._config.mindtct_executable), str(source), str(root)),
            workspace=workspace,
            budget=budget,
            tool=MINDTCT_TOOL,
            stage=EXTRACTION_STAGE,
        )
        timings[f"{side}_extraction"] = result.duration_ms

        if result.launch_failed:
            raise _StageFailure(
                launch_failure(tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE)
            )
        if result.timed_out:
            raise _StageFailure(
                timeout_failure(tool=MINDTCT_TOOL, stage=EXTRACTION_STAGE)
            )
        if is_process_crash(result.exit_code):
            raise _StageFailure(
                crash_failure(
                    tool=MINDTCT_TOOL,
                    stage=EXTRACTION_STAGE,
                    exit_code=int(result.exit_code or 0),
                )
            )
        if result.exit_code != 0:
            raise _StageFailure(
                extraction_exit_failure(side=side, exit_code=int(result.exit_code or 0))
            )

        template = workspace.work_path(f"{output_root}.xyt")
        try:
            minutiae = read_xyt(
                template, image_width=raster.width, image_height=raster.height
            )
        except XytFormatError as exc:
            raise _StageFailure(
                invalid_extractor_output_failure(side=side, kind=exc.kind)
            ) from exc
        counts[f"{side}_minutiae_count"] = str(len(minutiae))
        return template

    def _match(
        self,
        *,
        left_template: Path,
        right_template: Path,
        workspace: AdapterJobWorkspace,
        budget: "_Budget",
        timings: dict[str, float],
    ) -> int:
        """``bozorth3 <probe.xyt> <gallery.xyt>``, with no options at all.

        The first argument is the probe and the second is the gallery, which is
        BOZORTH3's own definition. No ``-m1``, no ``-n``, no ``-A``, no ``-T``, no
        ``-q``, no ``-o``, no ``-e`` and no ``-v``: a threshold would filter the
        output and stop this being a raw-score run at all (spec sections 24, 25).
        """
        result = self._run(
            argv=(
                str(self._config.bozorth3_executable),
                str(left_template),
                str(right_template),
            ),
            workspace=workspace,
            budget=budget,
            tool=BOZORTH3_TOOL,
            stage=MATCHING_STAGE,
        )
        timings["matching"] = result.duration_ms

        if result.launch_failed:
            raise _StageFailure(
                launch_failure(tool=BOZORTH3_TOOL, stage=MATCHING_STAGE)
            )
        if result.timed_out:
            raise _StageFailure(
                timeout_failure(tool=BOZORTH3_TOOL, stage=MATCHING_STAGE)
            )
        if is_process_crash(result.exit_code):
            raise _StageFailure(
                crash_failure(
                    tool=BOZORTH3_TOOL,
                    stage=MATCHING_STAGE,
                    exit_code=int(result.exit_code or 0),
                )
            )
        if result.exit_code != 0:
            raise _StageFailure(
                matching_exit_failure(exit_code=int(result.exit_code or 0))
            )

        try:
            return parse_bozorth3_score(result.stdout)
        except ScoreFormatError as exc:
            raise _StageFailure(no_score_failure(detail=exc.detail)) from exc

    def _run(
        self,
        *,
        argv: tuple[str, ...],
        workspace: AdapterJobWorkspace,
        budget: "_Budget",
        tool: str,
        stage: str,
    ) -> ExternalCommandResult:
        remaining = budget.remaining()
        if remaining <= 0:
            raise _StageFailure(timeout_failure(tool=tool, stage=stage))
        return run_external_command(
            ExternalCommand(
                argv=argv,
                working_directory=workspace.working_directory,
                containment_root=workspace.working_directory,
                timeout_seconds=max(remaining, _MINIMUM_BUDGET_SECONDS),
            )
        )

    # -------------------------------------------------------------- cleanup

    def _cleanup(self, workspace: AdapterJobWorkspace) -> None:
        """Remove everything this comparison wrote, on every path out.

        The runner does not empty the working directory between jobs, so an
        adapter that left its templates behind would accumulate two files per
        comparison for six thousand comparisons — and would be publishing
        intermediate biometric data by accident (spec section 32).

        Scoped, not wildcarded: the staged inputs by name, and then anything whose
        name is one of the two known output roots or begins with it. That catches
        an output the official build writes and this list does not name, without
        ever touching a file outside the two roots.
        """
        directory = workspace.working_directory
        prefixes = tuple(f"{root}." for root in (LEFT_OUTPUT_ROOT, RIGHT_OUTPUT_ROOT))
        exact = {LEFT_INPUT, RIGHT_INPUT, LEFT_OUTPUT_ROOT, RIGHT_OUTPUT_ROOT}
        try:
            entries = list(directory.iterdir())
        except OSError:  # pragma: no cover - the runner created it
            return
        for entry in entries:
            name = entry.name
            if name not in exact and not name.startswith(prefixes):
                continue
            try:
                if entry.is_symlink() or entry.is_file():
                    entry.unlink()
            except OSError:  # pragma: no cover - nothing else holds these
                continue

    # ------------------------------------------------------------- helpers

    def _unavailable(self, message: str) -> EnvironmentReport:
        return EnvironmentReport(
            status=EnvironmentStatus.UNAVAILABLE,
            implementation_version=IMPLEMENTATION_VERSION,
            runtime={},
            dependencies={},
            message=message,
        )

    def _manifest_problem(self, message: str) -> EnvironmentReport:
        """An uncertified build: reported in development, refused in research.

        A research run whose executables are not the ones NIST's own tests were
        run against has nothing to attribute its scores to, and there is no
        version of that which is merely "unavailable" (spec section 12).
        """
        if self._config.research_mode:
            raise ResearchPreflightError(
                f"the pinned NBIS build is not certified: {message}"
            )
        return self._unavailable(message)


class _Budget:
    """The comparison's remaining time, shared across its three subprocesses.

    One budget rather than one per stage: the contract gives the adapter a total
    for the whole comparison — staging, both extractions, the match and the
    checks in between — and three independent timeouts would let a comparison
    take three times it. Monotonic, so a clock adjustment cannot extend it
    (spec section 29).
    """

    def __init__(self, total_seconds: float) -> None:
        self._total = float(total_seconds)
        self._started = perf_counter_ns()

    def remaining(self) -> float:
        elapsed = (perf_counter_ns() - self._started) / 1_000_000_000
        return self._total - elapsed


def version_probe(executable: Path, probe: tuple[str, ...]) -> str | None:
    """Ask a tool what it is, in a directory it cannot pollute.

    Returns the normalised output, or ``None`` when the tool could not be run at
    all. Whatever the tool chooses to print is recorded by the build and compared
    here; the value of the check is that the answer is *stable*, not that it is
    prose (spec section 18).
    """
    scratch = Path(tempfile.mkdtemp(prefix="fpbench-nbis-probe-"))
    try:
        result = run_external_command(
            ExternalCommand(
                argv=(str(executable), *probe),
                working_directory=scratch,
                containment_root=scratch,
                timeout_seconds=_VERSION_PROBE_TIMEOUT_SECONDS,
            )
        )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if result.launch_failed or result.timed_out:
        return None
    return "\n".join(
        line.strip()
        for line in (result.stdout + result.stderr).splitlines()
        if line.strip()
    )[:2000]


def _digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(_READ_CHUNK), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
