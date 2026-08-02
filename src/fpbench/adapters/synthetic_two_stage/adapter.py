"""Extract, extract, match — behind the same three methods as everything else.

The point of this adapter is what it does *not* need. It runs three subprocesses
per comparison, writes four intermediate files, and can fail at four different
stages; and it reaches the runner through ``descriptor``,
``validate_environment`` and ``compare``, exactly as the dummy matcher does.
``SingleJobRunner`` gains no extractor, no matcher, no template store and no
knowledge that this route has stages at all (docs/adr/0039, docs/adr/0043).

The sequence, per comparison:

    left  PreparedImage -> converted input -> extractor -> left template
    right PreparedImage -> converted input -> extractor -> right template
    left template + right template          -> matcher   -> raw score

Both sides are extracted independently, always. A SELF comparison hands in the
same image twice and gets two separate extractions, because reusing the first
would make SELF the one stage that took a different code path — and SELF exists
precisely to detect the failures that have nothing to do with cross-impression
matching (docs/adr/0035, spec section 30).

Nothing is cached and nothing is persisted. The templates live under
``context.working_directory`` and are gone with it; there is no template store,
no cross-pair reuse and no shared state between comparisons (docs/adr/0041).

**No score here means anything about two fingerprints.** The tools underneath
hash bytes.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from time import perf_counter_ns
from typing import Mapping

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION, FingerprintAlgorithmAdapter
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
from fpbench.adapters.synthetic_two_stage.config import SyntheticTwoStageConfig
from fpbench.adapters.synthetic_two_stage.failure_mapping import (
    extraction_failure,
    launch_failure,
    matching_failure,
    missing_template_failure,
    no_score_failure,
    timeout_failure,
)
from fpbench.core.enums import EnvironmentStatus, ScoreDirection
from fpbench.core.errors import RuntimeDriftError
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
    "SyntheticTwoStageCliAdapter",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "EXTRACTOR_ROLE",
    "MATCHER_ROLE",
    "PIPELINE",
    "IMPLEMENTATION_VERSION",
]

ALGORITHM_ID = "synthetic_two_stage_cli"
ADAPTER_ID = "synthetic_two_stage_cli"

IMPLEMENTATION_VERSION = "fixture-1"

#: Two roles, because two files can each change a score. A bundle holding only
#: one of them is not this route's runtime (docs/adr/0042).
EXTRACTOR_ROLE = "synthetic_extractor"
MATCHER_ROLE = "synthetic_matcher"

#: The identity of the whole route, not of the matcher. ``extractor_id`` and
#: ``matcher_id`` differ here, which is the case SourceAFIS could not exercise
#: and NBIS will be (docs/adr/0014, spec section 68).
PIPELINE = AlgorithmPipelineMetadata(
    family_id="fpbench_fixture",
    pipeline_kind="extract_then_match",
    extractor_id="synthetic_cli_extractor",
    extractor_version=IMPLEMENTATION_VERSION,
    matcher_id="synthetic_cli_matcher",
    matcher_version=IMPLEMENTATION_VERSION,
    implementation_language="python",
    integration_mode="subprocess_per_stage",
    input_mode="converted_file",
    dpi_policy="explicit_effective_ppi",
    probe_side="left",
    template_cache="disabled",
    template_persistence="disabled",
    seed_usage="ignored_algorithm_has_no_seed",
)

#: Intermediate file names. Deliberately meaningless: the adapter has no subject,
#: no finger and no pair, and a name that carried one would mean it had been
#: given something it must not have (spec section 35).
LEFT_INPUT = "left-input.bin"
RIGHT_INPUT = "right-input.bin"
LEFT_TEMPLATE = "left-template.xyt"
RIGHT_TEMPLATE = "right-template.xyt"

_SCORE = re.compile(r"^score=(?P<value>[-+]?\d+(?:\.\d+)?)\s*$", re.MULTILINE)

_NS_PER_MS = 1_000_000

#: Never let a stage run to zero budget: a zero timeout is not a valid command,
#: and "there was no time left" is a timeout rather than a configuration error.
_MINIMUM_BUDGET_SECONDS = 0.001


class _StageFailure(Exception):
    """Internal: stop the comparison and record ``info``."""

    def __init__(self, info: FailureInfo) -> None:
        super().__init__(info.message)
        self.info = info


class SyntheticTwoStageCliAdapter(FingerprintAlgorithmAdapter):
    """Compares two prepared images with a separate extractor and matcher."""

    def __init__(self, config: SyntheticTwoStageConfig) -> None:
        self._config = config
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="Synthetic two-stage CLI fixture",
            adapter_id=ADAPTER_ID,
            adapter_version="1",
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=IMPLEMENTATION_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            capabilities=(),
            metadata=PIPELINE.as_descriptor_metadata(),
        )
        #: Taken during environment validation, compared before every comparison.
        self._runtime: Mapping[str, FileIdentity] | None = None

    @classmethod
    def from_config(
        cls, config: Mapping[str, object]
    ) -> "SyntheticTwoStageCliAdapter":
        return cls(SyntheticTwoStageConfig.from_mapping(config))

    @property
    def config(self) -> SyntheticTwoStageConfig:
        return self._config

    @property
    def descriptor(self) -> AlgorithmDescriptor:
        return self._descriptor

    # ---------------------------------------------------------- environment

    def validate_environment(self) -> EnvironmentReport:
        """Are both tools and the interpreter present?

        A missing tool is reported, never raised: it is one fault of the run, not
        one failure per pair. In research mode the two tools' identities are
        recorded here, so that a replacement half way through a run is noticed by
        the cheap per-comparison check.
        """
        self._runtime = None
        missing = [
            name
            for name, path in (
                ("interpreter", self._config.interpreter),
                ("extractor", self._config.extractor),
                ("matcher", self._config.matcher),
            )
            if not Path(path).is_file()
        ]
        if missing:
            return EnvironmentReport(
                status=EnvironmentStatus.UNAVAILABLE,
                implementation_version=IMPLEMENTATION_VERSION,
                runtime={},
                dependencies={},
                # No absolute path: an environment report is shown to people and
                # stored beside results.
                message=f"the two-stage fixture is missing: {missing}",
            )

        try:
            self._runtime = snapshot_runtime_assets(self._config.runtime_assets())
        except RuntimeDriftError as exc:  # pragma: no cover - it existed a moment ago
            return EnvironmentReport(
                status=EnvironmentStatus.UNAVAILABLE,
                implementation_version=IMPLEMENTATION_VERSION,
                runtime={},
                dependencies={},
                message=str(exc),
            )

        return EnvironmentReport(
            status=EnvironmentStatus.READY,
            implementation_version=IMPLEMENTATION_VERSION,
            runtime=dict(runtime_description()),
            dependencies={
                f"{EXTRACTOR_ROLE}.size": str(self._runtime[EXTRACTOR_ROLE].size_bytes),
                f"{MATCHER_ROLE}.size": str(self._runtime[MATCHER_ROLE].size_bytes),
            },
        )

    def check_runtime_integrity(self) -> None:
        """Confirm both tools are still the files preflight approved.

        Two ``stat`` calls, not two re-hashes: this runs before every comparison
        and the full digest runs before and after the executor. Outside research
        mode there is nothing pinned and nothing to check.

        Raises:
            RuntimeDriftError: either tool changed. Fatal to the invocation —
                never a comparison failure (docs/adr/0018).
        """
        if not self._config.research_mode:
            return
        if self._runtime is None:
            raise RuntimeDriftError(
                "the two-stage runtime was never validated; a research "
                "comparison cannot be attributed to unchecked tools"
            )
        require_runtime_assets_unchanged(
            self._config.runtime_assets(), self._runtime, label="two-stage tool"
        )

    # -------------------------------------------------------------- compare

    def compare(
        self,
        left: PreparedImage,
        right: PreparedImage,
        context: ComparisonContext,
    ) -> RawMatchResult:
        """Convert, extract twice, match once.

        ``left`` is the probe and ``right`` the candidate, fixed. No reversal, no
        averaging of the two directions, no maximum of the two.

        Raises:
            RuntimeDriftError: in research mode, when a tool is no longer the
                file preflight approved. Deliberately the one thing this method
                raises instead of recording.
        """
        self.check_runtime_integrity()

        workspace = AdapterJobWorkspace.from_context(context)
        budget = _Budget(context.timeout_seconds)
        timings: dict[str, float] = {}

        try:
            started = perf_counter_ns()
            left_input = self._convert(left, workspace, LEFT_INPUT)
            right_input = self._convert(right, workspace, RIGHT_INPUT)
            timings["input_conversion"] = (perf_counter_ns() - started) / _NS_PER_MS

            left_template = self._extract(
                side="left",
                source=left_input,
                target=workspace.work_path(LEFT_TEMPLATE),
                workspace=workspace,
                budget=budget,
                timings=timings,
            )
            # Independently, even when both sides are the same file. The count is
            # recorded below so that this is a fact in the stored result rather
            # than a claim in a docstring (spec section 31).
            right_template = self._extract(
                side="right",
                source=right_input,
                target=workspace.work_path(RIGHT_TEMPLATE),
                workspace=workspace,
                budget=budget,
                timings=timings,
            )
            score = self._match(
                left_template=left_template,
                right_template=right_template,
                workspace=workspace,
                budget=budget,
                timings=timings,
            )
        except _StageFailure as failure:
            return RawMatchResult.failed(
                failure=failure.info,
                score_direction=ScoreDirection.HIGHER_IS_BETTER,
                artifacts=(),
                timing_components_ms=timings,
                metadata=self._metadata(left, right),
            )

        return RawMatchResult.success(
            raw_score=score,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            artifacts=(),
            timing_components_ms=timings,
            metadata=self._metadata(left, right),
        )

    # -------------------------------------------------------------- stages

    def _convert(
        self, image: PreparedImage, workspace: AdapterJobWorkspace, name: str
    ) -> Path:
        """Copy the prepared image into the job's own directory.

        A stand-in for whatever a real tool needs done to its input before it can
        read it. It is deliberately a *copy* and nothing more: the adapter must
        never write into a dataset file or a prepared artefact, and the
        conformance suite checks the source bytes afterwards.

        This used to say MINDTCT needs a PGM. It does not: the NBIS 5.0.0
        certification route hands MINDTCT the prepared 8-bit greyscale PNG byte
        for byte, and stage 7B verified direct PNG input on the official build
        before relying on it (docs/adr/0048, spec section 21).
        """
        target = workspace.work_path(name)
        try:
            shutil.copyfile(Path(image.local_path), target)
        except OSError as exc:
            raise _StageFailure(
                launch_failure(stage="input conversion", detail=type(exc).__name__)
            ) from exc
        return target

    def _extract(
        self,
        *,
        side: str,
        source: Path,
        target: Path,
        workspace: AdapterJobWorkspace,
        budget: "_Budget",
        timings: dict[str, float],
    ) -> Path:
        result = self._run(
            argv=(str(self._config.interpreter), str(self._config.extractor),
                  str(source), str(target)),
            workspace=workspace,
            budget=budget,
            stage=f"{side} extraction",
        )
        timings[f"{side}_extraction"] = result.duration_ms

        if result.launch_failed:
            raise _StageFailure(
                launch_failure(stage=f"{side} extraction", detail=result.stderr)
            )
        if result.timed_out:
            raise _StageFailure(timeout_failure(stage=f"{side} extraction"))
        if result.exit_code != 0:
            raise _StageFailure(
                extraction_failure(
                    side=side,
                    exit_code=int(result.exit_code or 0),
                    stderr=result.stderr,
                )
            )
        # Step 3 of the precedence order: the tool claimed success, so its exit
        # code says nothing; the output file is what decides.
        if not target.is_file() or target.stat().st_size == 0:
            raise _StageFailure(missing_template_failure(side=side))
        return target

    def _match(
        self,
        *,
        left_template: Path,
        right_template: Path,
        workspace: AdapterJobWorkspace,
        budget: "_Budget",
        timings: dict[str, float],
    ) -> float:
        result = self._run(
            argv=(str(self._config.interpreter), str(self._config.matcher),
                  str(left_template), str(right_template)),
            workspace=workspace,
            budget=budget,
            stage="matching",
        )
        timings["matching"] = result.duration_ms

        if result.launch_failed:
            raise _StageFailure(
                launch_failure(stage="matching", detail=result.stderr)
            )
        if result.timed_out:
            raise _StageFailure(timeout_failure(stage="matching"))
        if result.exit_code != 0:
            raise _StageFailure(
                matching_failure(
                    exit_code=int(result.exit_code or 0), stderr=result.stderr
                )
            )

        match = _SCORE.search(result.stdout)
        if match is None:
            raise _StageFailure(no_score_failure(stdout_excerpt=result.stdout))
        return float(match.group("value"))

    def _run(
        self,
        *,
        argv: tuple[str, ...],
        workspace: AdapterJobWorkspace,
        budget: "_Budget",
        stage: str,
    ) -> ExternalCommandResult:
        remaining = budget.remaining()
        if remaining <= 0:
            raise _StageFailure(timeout_failure(stage=stage))
        return run_external_command(
            ExternalCommand(
                argv=argv,
                working_directory=workspace.working_directory,
                containment_root=workspace.working_directory,
                timeout_seconds=max(remaining, _MINIMUM_BUDGET_SECONDS),
            )
        )

    # ------------------------------------------------------------ metadata

    def _metadata(
        self, left: PreparedImage, right: PreparedImage
    ) -> Mapping[str, str]:
        """What the stored result records about how this score was produced.

        The four independence keys are mandatory for this route and its validator
        demands them: a two-stage adapter that quietly cached a template would
        make every SELF comparison meaningless, and the only way to know it did
        not is for the result to say so (spec section 31).
        """
        return {
            "integration_mode": PIPELINE.integration_mode,
            "input_mode": PIPELINE.input_mode,
            "dpi_policy": PIPELINE.dpi_policy,
            "probe_side": PIPELINE.probe_side,
            "left_dpi": str(left.effective_ppi),
            "right_dpi": str(right.effective_ppi),
            "extraction_policy": "independent_both_sides",
            "extraction_count": "2",
            "template_cache": "disabled",
            "template_persistence": "disabled",
            "extractor_version": PIPELINE.extractor_version,
            "matcher_version": PIPELINE.matcher_version,
        }


class _Budget:
    """The comparison's remaining time, shared across its three subprocesses.

    One budget rather than one per stage: the contract gives the adapter a total,
    and three independent timeouts would let a comparison take three times it.
    """

    def __init__(self, total_seconds: float) -> None:
        self._total = float(total_seconds)
        self._started = perf_counter_ns()

    def remaining(self) -> float:
        elapsed = (perf_counter_ns() - self._started) / 1_000_000_000
        return self._total - elapsed
