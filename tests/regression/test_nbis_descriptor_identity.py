"""The NBIS route's identity is pinned, and stage 7C did not move it.

Stage 7B decided what this algorithm *is*: MINDTCT into BOZORTH3 as one identity,
version 5.0.0, contract v1, adapter v1, higher-is-better, deterministic, with a
named list of tool options it deliberately does not pass (docs/adr/0046,
docs/adr/0049). Stage 7C runs it over 6,000 comparisons and attributes every one
of them to that identity through `algorithm_fingerprint`.

So the fingerprint is written down here as a constant. If a later change moves it
— a version string, a capability, a metadata key, an option that starts being
passed — every stored result would be attributed to an algorithm that no longer
exists under that name, and this test says so before the results do
(spec section 15).

The value below is derived from constants and is independent of where the build
lives, which is why this test needs no NBIS, no build and no workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpbench.adapters.nbis.adapter import (
    ADAPTER_ID,
    ALGORITHM_ID,
    IMPLEMENTATION_VERSION,
    NbisAdapter,
)
from fpbench.adapters.nbis.config import NbisConfig
from fpbench.core.enums import ScoreDirection
from fpbench.core.execution_models import descriptor_fingerprint

pytestmark = [pytest.mark.nbis_contract, pytest.mark.adapter_contract]

#: Computed once, from the descriptor the certified adapter reports. Stage 7C's
#: 6,000 results carry this value in `algorithm_fingerprint`.
NBIS_DESCRIPTOR_FINGERPRINT = (
    "41ebe6eeda877e959d58df40d007daab74a8a1a560462984a6f58a444dbfebc5"
)


def descriptor(root: str = "/opt/nbis", research_mode: bool = False):
    base = Path(root).resolve()
    return NbisAdapter(
        NbisConfig(
            mindtct_executable=base / "bin" / "mindtct",
            bozorth3_executable=base / "bin" / "bozorth3",
            build_manifest=base / "nbis-build-manifest.json",
            research_mode=research_mode,
        )
    ).descriptor


def test_the_descriptor_fields_are_the_ones_stage_7b_decided():
    reported = descriptor()
    assert reported.algorithm_id == ALGORITHM_ID == "nbis_mindtct_bozorth3"
    assert reported.adapter_id == ADAPTER_ID == "nbis_mindtct_bozorth3_subprocess"
    assert reported.adapter_version == "1"
    assert reported.adapter_contract_version == "1"
    assert reported.implementation_version == IMPLEMENTATION_VERSION == "5.0.0"
    assert reported.score_direction is ScoreDirection.HIGHER_IS_BETTER
    assert reported.deterministic is True


def test_the_descriptor_fingerprint_did_not_move():
    assert descriptor_fingerprint(descriptor()) == NBIS_DESCRIPTOR_FINGERPRINT


def test_the_fingerprint_does_not_depend_on_where_the_build_lives():
    """A build directory is a fact about a machine, not about the algorithm."""
    assert descriptor_fingerprint(descriptor("/opt/nbis")) == descriptor_fingerprint(
        descriptor("/home/someone/builds/nbis-5.0.0/658f9f54a8f2")
    )


def test_research_mode_does_not_change_what_the_algorithm_is():
    """Pinning moves where the bytes live, not which algorithm they are."""
    assert descriptor_fingerprint(
        descriptor(research_mode=True)
    ) == NBIS_DESCRIPTOR_FINGERPRINT


def test_stage_7c_creates_no_descriptor_of_its_own():
    """Section 15: there is no special descriptor for the full run."""
    import ast

    from fpbench.experiments import nbis_canonical500_full

    source = Path(nbis_canonical500_full.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            target = node.func
            name = (
                target.id
                if isinstance(target, ast.Name)
                else getattr(target, "attr", "")
            )
            assert name != "AlgorithmDescriptor", (
                "the full run uses the adapter's own descriptor"
            )
