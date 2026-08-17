"""The capacity-extended variant: the same route against a modified OpenAFIS.

Stage 19A found that OpenAFIS refuses any template above its declared
``MaximumMinutiae = 128``, and that 95.1% of rolled SD300 impressions exceed it.
Stage 19B tests one hypothesis and one only: does the composition become usable if
that *refusal* is removed and nothing else changes?

**This is a sibling module, not an edit.** ``adapter.py`` is pinned byte-for-byte
by Stage 19A's published marker, so the variant subclasses it rather than
parameterising it. Everything that decides a score — MINDTCT and its flags, the
XYT parser, the translation rules, the matching algorithm, the probe side, the
score contract — is inherited unchanged.

**The identity must change, and does.** The score now comes from a build that does
not behave like upstream, so calling it ``nbis_mindtct_openafis`` would attribute
our modification to OpenAFIS. Section 4 of the requirements is explicit about
this, and the descriptor carries the modification in its own metadata rather than
only in a document beside it.

WHAT WAS MODIFIED, EXACTLY

.. code-block:: text

    lib/Template.cpp, Template<I, F>::load()

    +#ifndef FPBENCH_STAGE19B_ALLOW_ABOVE_MAXIMUM_MINUTIAE
         if (minutiae.size() > MaximumMinutiae) {
             Log::error("minutiea count > MaximumMinutiae");
             return false;
         }
    +#endif

Two lines, in one file. The constant ``MaximumMinutiae`` is **not** changed to 256
or 512: it also sizes the ISO parser's ``reserve`` and its ``MaximumLength``, and
Stage 19B has no business altering the ISO route. The CSV reader loads all its
minutiae before ``Template::load`` is reached, so disabling the refusal is the
whole change for this route.

``MinimumMinutiae = 2`` is untouched. Only the upper bound is removed.

WHAT THIS BUILD IS NOT

Validated by upstream above 128 minutiae. Upstream refuses that region, so there
is no upstream behaviour to agree with. What Gate A establishes is narrower and
worth stating precisely: over all 1,583 comparisons that the *unmodified* build
already scored, the patched build returns byte-identical scores.
"""

from __future__ import annotations

import math
from pathlib import Path
from time import perf_counter_ns
from typing import Mapping, Sequence

from fpbench.adapters.base import ADAPTER_CONTRACT_VERSION
from fpbench.adapters.nbis.xyt import NbisMinutia
from fpbench.adapters.openafis.adapter import (
    IMPLEMENTATION_VERSION as BASE_IMPLEMENTATION_VERSION,
)
from fpbench.adapters.openafis.adapter import (
    OPENAFIS_COMMIT,
    PIPELINE_METADATA as BASE_PIPELINE_METADATA,
)
from fpbench.adapters.openafis.adapter import (
    RESULT_METADATA as BASE_RESULT_METADATA,
)
from fpbench.adapters.openafis.adapter import OpenAfisAdapter, _StageFailure
from fpbench.adapters.openafis.config import OpenAfisConfig
from fpbench.adapters.openafis.failure_mapping import (
    infrastructure_failure,
    template_refused_failure,
)
from fpbench.adapters.openafis.translation import (
    OPENAFIS_MINIMUM_MINUTIAE,
    PLACEHOLDER_MINUTIA_TYPE,
    TranslatedTemplate,
    TranslationRefused,
)
from fpbench.adapters.support.workspace import AdapterJobWorkspace
from fpbench.core.enums import FailureCode, FailureStage, ScoreDirection
from fpbench.core.execution_models import AlgorithmDescriptor

__all__ = [
    "OpenAfisCapacityExtendedAdapter",
    "ALGORITHM_ID",
    "ADAPTER_ID",
    "ADAPTER_VERSION",
    "IMPLEMENTATION_VERSION",
    "BASE_OPENAFIS_COMMIT",
    "UPSTREAM_MODIFIED",
    "MODIFICATION",
    "PIPELINE_METADATA",
    "RESULT_METADATA",
    "translate_xyt_to_openafis_csv_uncapped",
]

ALGORITHM_ID = "nbis_mindtct_openafis_capacity_extended"
ADAPTER_ID = "nbis_mindtct_openafis_capacity_extended_subprocess"
ADAPTER_VERSION = "1.0.0"

BASE_OPENAFIS_COMMIT = OPENAFIS_COMMIT
UPSTREAM_MODIFIED = True
MODIFICATION = "disable_template_upper_minutiae_rejection_for_stage19b_csv_route"

IMPLEMENTATION_VERSION = f"{BASE_IMPLEMENTATION_VERSION}+capacity-extended"

#: The base pipeline, plus the three fields that say this is not upstream. Nothing
#: that decides a score differs from the base route.
PIPELINE_METADATA: Mapping[str, str] = {
    **dict(BASE_PIPELINE_METADATA),
    "matcher_id": "openafis_capacity_extended",
    "upstream_modified": "true",
    "base_openafis_commit": BASE_OPENAFIS_COMMIT,
    "modification": MODIFICATION,
    "openafis_minutiae_bounds": "2..unbounded",
    "openafis_minimum_minutiae": "2",
    "openafis_over_maximum_policy": "accept — the upstream refusal is disabled",
    "shares_extractor_with": "nbis_mindtct_bozorth3",
}

RESULT_METADATA: Mapping[str, str] = {
    **dict(BASE_RESULT_METADATA),
    "pipeline": ALGORITHM_ID,
    "matcher": "openafis_capacity_extended",
    "upstream_modified": "true",
    "base_openafis_commit": BASE_OPENAFIS_COMMIT,
    "modification": MODIFICATION,
}


_NS_PER_MS = 1_000_000


def translate_xyt_to_openafis_csv_uncapped(
    minutiae: Sequence[NbisMinutia],
    *,
    width: int,
    height: int,
    minutia_type: int = PLACEHOLDER_MINUTIA_TYPE,
) -> TranslatedTemplate:
    """:func:`translate_xyt_to_openafis_csv`, minus the upper bound. Nothing else.

    Removing OpenAFIS's refusal in C++ is only half the experiment: fpbench's own
    translator enforced the same 128 ceiling before a template ever reached the
    matcher, so the patched build would never have been asked the question.
    Section 9 is explicit — *every* minutia MINDTCT produced goes to OpenAFIS.

    This is a sibling rather than a parameter because
    :mod:`fpbench.adapters.openafis.translation` is pinned byte-for-byte by Stage
    19A's published marker. The two functions are proved to agree exactly for
    every count the base one accepts, in ``tests/test_stage19b_contract.py`` —
    the module-level analogue of Gate A.

    The lower bound stays: a template with fewer than two minutiae is still
    refused, because upstream still refuses it and Stage 19B removes only the
    upper limit.
    """
    if width <= 0 or height <= 0:
        raise TranslationRefused("invalid_raster_dimensions", f"{width}x{height}")

    count = len(minutiae)
    if count < OPENAFIS_MINIMUM_MINUTIAE:
        raise TranslationRefused(
            "minutiae_below_upstream_minimum", f"{count} < {OPENAFIS_MINIMUM_MINUTIAE}"
        )
    # No upper-bound check here. That is the entire difference, and it is the
    # entire point of Stage 19B.

    lines = [f"{width},{height}"]
    for minutia in minutiae:
        radians = minutia.theta * math.pi / 180.0
        lines.append(f"{minutia_type},{minutia.x},{minutia.y},{radians:.9f}")

    return TranslatedTemplate(text="\n".join(lines) + "\n", minutiae_count=count)


class OpenAfisCapacityExtendedAdapter(OpenAfisAdapter):
    """Stage 19A's adapter, pointed at a build whose upper bound is disabled.

    Only the identity is overridden. ``compare`` is inherited without change, so
    the extraction, the translation, the probe side, the failure vocabulary and
    the score contract are literally the same code that produced Stage 19A.
    """

    def __init__(self, config: OpenAfisConfig) -> None:
        super().__init__(config)
        self._descriptor = AlgorithmDescriptor(
            algorithm_id=ALGORITHM_ID,
            display_name="NBIS MINDTCT + OpenAFIS (capacity-extended)",
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            adapter_contract_version=ADAPTER_CONTRACT_VERSION,
            implementation_version=IMPLEMENTATION_VERSION,
            score_direction=ScoreDirection.HIGHER_IS_BETTER,
            deterministic=True,
            capabilities=(),
            metadata=PIPELINE_METADATA,
        )

    @classmethod
    def from_config(cls, config: Mapping[str, object]) -> "OpenAfisCapacityExtendedAdapter":
        return cls(OpenAfisConfig.from_mapping(config))

    def validate_environment(self):
        """The base check, re-labelled with *this* build's implementation version.

        ``validate_environment`` is inherited, and the base one names the module
        constant of the unmodified route. Left alone, a capacity-extended run
        would record ``nbis-5.0.0+openafis-3ae1c757`` in its environment report
        and be attributed to a build that refuses templates this one accepts.

        The shared adapter conformance suite catches exactly this: it requires the
        descriptor's implementation version and the environment report's to agree.
        """
        from dataclasses import replace

        report = super().validate_environment()
        if report.implementation_version == IMPLEMENTATION_VERSION:
            return report
        return replace(report, implementation_version=IMPLEMENTATION_VERSION)

    def _translate(
        self, *, side: str, minutiae, raster, workspace: AdapterJobWorkspace,
        name: str, timings: dict[str, float],
    ) -> Path:
        """The base method, using the uncapped translator.

        Overridden rather than edited in place: the base ``_translate`` lives in a
        file Stage 19A's marker pins. The body is otherwise identical, including
        the timing key and the failure it raises when the *lower* bound is broken.
        """
        started = perf_counter_ns()
        try:
            translated = translate_xyt_to_openafis_csv_uncapped(
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
                    stage=FailureStage.EXTRACTION, code=FailureCode.INTERNAL_ERROR,
                    detail=type(exc).__name__,
                )
            ) from exc
        timings[f"openafis_template_{side}"] = (perf_counter_ns() - started) / _NS_PER_MS
        return target
